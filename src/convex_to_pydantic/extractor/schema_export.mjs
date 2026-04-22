#!/usr/bin/env node
/**
 * Convex schema extractor.
 *
 * Walks the user's `convex/` directory directly, importing each module file
 * to discover queries, mutations, and actions. Works whether or not
 * `npx convex dev` has been run — we don't rely on `_generated/api.js` being
 * populated. TypeScript is supported via `esbuild` (a transitive dep of the
 * `convex` npm package).
 *
 * Emits `{"tables": [...], "functions": [...]}` on stdout. Module paths use
 * forward slashes on every platform. Entries are sorted by (module, name) /
 * tableName for deterministic output.
 *
 * Usage:
 *   node schema_export.mjs --convex-dir ./convex
 */

import { createRequire } from "module";
import { readdirSync, readFileSync, writeFileSync, mkdirSync, rmSync, existsSync } from "fs";
import { tmpdir } from "os";
import { createHash } from "crypto";
import { resolve, join, sep, relative, extname, dirname, basename } from "path";
import { pathToFileURL } from "url";

// ---------------------------------------------------------------------------
// Args
// ---------------------------------------------------------------------------

const args = process.argv.slice(2);
let convexDir = null;
for (let i = 0; i < args.length; i++) {
  if (args[i] === "--convex-dir" && i + 1 < args.length) {
    convexDir = resolve(args[i + 1]);
    i++;
  }
}
if (!convexDir) {
  console.error("Usage: node schema_export.mjs --convex-dir <path>");
  process.exit(1);
}
if (!existsSync(convexDir)) {
  console.error(`Error: convex directory not found: ${convexDir}`);
  process.exit(1);
}

// createRequire scoped to the user's project so we can resolve packages
// from their node_modules. We anchor at `convexDir` itself, which lets
// Node walk up to find the nearest node_modules (works for npm flat layouts
// and for pnpm projects where the lockfile lives at the project root).
const userRequire = createRequire(join(convexDir, "__c2p_anchor__"));

// ---------------------------------------------------------------------------
// Cache dir for transpiled TypeScript
// ---------------------------------------------------------------------------

// We put the cache INSIDE convexDir (rather than in /tmp) so that:
//   - Node's `node_modules` lookup still walks up to the user's project
//     and resolves packages like `convex` / `convex/values` correctly.
//   - esbuild's bundle step inlines relative imports (./_generated/server)
//     so the cache-file layout doesn't need to mirror the original tree.
const CACHE_DIR_NAME = ".c2p-cache";
const cacheRoot = join(convexDir, CACHE_DIR_NAME);
let cacheRootCreated = false;
function ensureCacheRoot() {
  if (!cacheRootCreated) {
    mkdirSync(cacheRoot, { recursive: true });
    cacheRootCreated = true;
  }
  return cacheRoot;
}
process.on("exit", () => {
  if (cacheRootCreated) {
    try {
      rmSync(cacheRoot, { recursive: true, force: true });
    } catch {
      /* best-effort cleanup */
    }
  }
});

// ---------------------------------------------------------------------------
// Exclusions
// ---------------------------------------------------------------------------

// Directories to skip when walking the convex dir.
const EXCLUDED_DIR_NAMES = new Set(["_generated", "node_modules"]);

// Filenames (stem.ext) to skip — Convex reserved modules and project config.
// Stem-based: we match `schema.ts`, `schema.js`, `schema.mjs`, etc.
const EXCLUDED_STEMS = new Set([
  "schema",
  "http",
  "crons",
  "auth.config",
  "convex.config",
]);

// Filenames (full) to skip — project metadata that happens to live under convex/.
const EXCLUDED_FILENAMES = new Set([
  "tsconfig.json",
  "package.json",
  "package-lock.json",
  "pnpm-lock.yaml",
  "yarn.lock",
]);

const MODULE_EXTS = new Set([".ts", ".js", ".mjs"]);

function isSkippedDir(name) {
  if (EXCLUDED_DIR_NAMES.has(name)) return true;
  if (name.startsWith("_")) return true;
  if (name.startsWith(".")) return true;
  return false;
}

function isSkippedFile(name) {
  if (name.startsWith("_")) return true;
  if (name.startsWith(".")) return true;
  if (name.endsWith(".d.ts")) return true;
  if (EXCLUDED_FILENAMES.has(name)) return true;
  const ext = extname(name);
  if (!MODULE_EXTS.has(ext)) return true;
  // Strip extension to check stem-based exclusions.
  const stem = name.slice(0, -ext.length);
  if (EXCLUDED_STEMS.has(stem)) return true;
  return false;
}

// ---------------------------------------------------------------------------
// Filesystem walk
// ---------------------------------------------------------------------------

/**
 * Recursively collect all user-authored module files under convexDir.
 * Returns [{absPath, modulePath, ext}, ...] with deterministic sort order.
 */
function collectModuleFiles(dir) {
  const results = [];
  walk(dir);
  results.sort((a, b) => (a.modulePath < b.modulePath ? -1 : a.modulePath > b.modulePath ? 1 : 0));
  return results;

  function walk(currentDir) {
    let entries;
    try {
      entries = readdirSync(currentDir, { withFileTypes: true });
    } catch (err) {
      console.error(`[convex-to-pydantic] Cannot read ${currentDir}: ${err.message}`);
      return;
    }
    for (const entry of entries) {
      if (entry.isDirectory()) {
        if (isSkippedDir(entry.name)) continue;
        walk(join(currentDir, entry.name));
      } else if (entry.isFile()) {
        if (isSkippedFile(entry.name)) continue;
        const absPath = join(currentDir, entry.name);
        const ext = extname(entry.name);
        const rel = relative(convexDir, absPath);
        const modulePath = rel.split(sep).join("/").slice(0, -ext.length);
        results.push({ absPath, modulePath, ext });
      }
    }
  }
}

// ---------------------------------------------------------------------------
// esbuild (lazy; only for .ts files)
// ---------------------------------------------------------------------------

let esbuild = null;
let esbuildLoadFailed = false;
function loadEsbuild() {
  if (esbuild) return esbuild;
  if (esbuildLoadFailed) return null;

  // Try the project root first (works for npm / yarn flat layouts and for
  // projects that declare esbuild as a direct dep).
  try {
    esbuild = userRequire("esbuild");
    return esbuild;
  } catch {
    /* fall through to the convex-scoped resolution */
  }

  // pnpm doesn't hoist transitive deps to the project root. Since esbuild is
  // a direct dep of the `convex` package, resolving it through convex's own
  // install dir works for pnpm layouts too.
  try {
    const convexPath = userRequire.resolve("convex/server");
    const convexRequire = createRequire(convexPath);
    esbuild = convexRequire("esbuild");
    return esbuild;
  } catch (err) {
    esbuildLoadFailed = true;
    console.error(
      "[convex-to-pydantic] Cannot resolve `esbuild` from your convex project's " +
        "node_modules. TypeScript modules cannot be imported. " +
        "Run `npm install` / `pnpm install` in your Convex project " +
        "(or add `esbuild` as a direct devDependency). " +
        `Underlying error: ${err.message}`
    );
    return null;
  }
}

/**
 * Bundle a .ts entrypoint to a self-contained .mjs inside the cache dir.
 *
 * Uses esbuild's bundle mode to inline all relative imports (so the output
 * doesn't depend on the original source-tree layout). `convex/*` imports are
 * kept external — they're resolved at runtime from the user's node_modules
 * (which works because the cache file lives inside the user's project).
 *
 * Returns the absolute path of the bundled file, or throws if esbuild isn't
 * available / transpilation fails.
 */
function bundleTsToCache(absPath) {
  const eb = loadEsbuild();
  if (!eb) throw new Error("esbuild unavailable");
  const hash = createHash("sha1").update(absPath).digest("hex").slice(0, 16);
  const outPath = join(
    ensureCacheRoot(),
    `${basename(absPath, extname(absPath))}-${hash}.mjs`
  );
  const result = eb.buildSync({
    entryPoints: [absPath],
    bundle: true,
    format: "esm",
    platform: "node",
    target: "es2022",
    // Keep convex and its subpath imports external so the user's installed
    // convex package is used at import time. Also keep bare specifiers
    // external (third-party npm deps the user might import).
    packages: "external",
    write: false,
    absWorkingDir: convexDir,
    outfile: outPath,
    logLevel: "silent",
  });
  // Write the single output file.
  const output = result.outputFiles.find((f) => f.path === outPath) || result.outputFiles[0];
  writeFileSync(outPath, output.contents);
  return outPath;
}

// ---------------------------------------------------------------------------
// Module import
// ---------------------------------------------------------------------------

async function importModule(absPath, ext) {
  if (ext === ".ts") {
    const jsPath = bundleTsToCache(absPath);
    return await import(pathToFileURL(jsPath).href);
  }
  return await import(pathToFileURL(absPath).href);
}

// ---------------------------------------------------------------------------
// Function detection + args extraction
// ---------------------------------------------------------------------------

function detectFunctionType(value) {
  // Convex function references are functions (produced by registration_impl's
  // `dontCallDirectly`) with marker properties attached. Accept both
  // functions and objects defensively.
  if (!value) return null;
  const t = typeof value;
  if (t !== "object" && t !== "function") return null;
  if (value.isQuery === true) return "query";
  if (value.isMutation === true) return "mutation";
  if (value.isAction === true) return "action";
  return null;
}

/**
 * Extract args schema from a Convex function reference. Uses Convex's
 * public `exportArgs()` method (returns a JSON-stringified validator) when
 * available, then falls back through the older private fields.
 */
function extractArgs(ref) {
  // Canonical path: exportArgs() is the Convex-public API.
  if (typeof ref.exportArgs === "function") {
    try {
      const exported = ref.exportArgs();
      if (typeof exported === "string") return JSON.parse(exported);
      if (exported && typeof exported === "object") return exported;
    } catch {
      // fall through
    }
  }
  // Older fallbacks for robustness against Convex internal changes.
  const v = ref._argsValidator ?? ref.argsValidator ?? null;
  if (v) {
    if (typeof v.json === "function") return v.json();
    if (typeof v.json === "object") return v.json;
    if (typeof v.export === "function") {
      try {
        const exp = v.export();
        return typeof exp === "string" ? JSON.parse(exp) : exp;
      } catch {
        /* fall through */
      }
    }
    if (v.kind || v.type) return validatorToJson(v);
  }
  // Empty-args default.
  return { type: "object", value: {} };
}

// ---------------------------------------------------------------------------
// Validator → JSON (used only by the schema fallback when .export() is absent)
// ---------------------------------------------------------------------------

function validatorToJson(validator) {
  if (!validator || typeof validator !== "object") return { type: "any" };
  const kind = validator.kind || validator.type;
  switch (kind) {
    case "string":
      return { type: "string" };
    case "number":
    case "float64":
      return { type: "number" };
    case "bigint":
    case "int64":
      return { type: "int64" };
    case "boolean":
      return { type: "boolean" };
    case "null":
      return { type: "null" };
    case "any":
      return { type: "any" };
    case "bytes":
      return { type: "bytes" };
    case "id":
      return { type: "id", tableName: validator.tableName };
    case "literal":
      return { type: "literal", value: validator.value };
    case "array":
      return { type: "array", value: validatorToJson(validator.element || validator.value) };
    case "record":
      return {
        type: "record",
        keys: validatorToJson(validator.keys),
        values: validatorToJson(validator.values),
      };
    case "union":
      return {
        type: "union",
        value: (validator.members || validator.value || []).map(validatorToJson),
      };
    case "object": {
      const fields = {};
      const fieldMap = validator.fields || validator.value || {};
      for (const [name, fieldValidator] of Object.entries(fieldMap)) {
        if (!fieldValidator || typeof fieldValidator !== "object") continue;
        if ("fieldType" in fieldValidator) {
          fields[name] = {
            fieldType: validatorToJson(fieldValidator.fieldType),
            optional: fieldValidator.optional || false,
          };
        } else if ("kind" in fieldValidator || "type" in fieldValidator) {
          fields[name] = {
            fieldType: validatorToJson(fieldValidator),
            optional: fieldValidator.isOptional === "optional",
          };
        }
      }
      return { type: "object", value: fields };
    }
    default:
      if (typeof validator.json === "function") return validator.json();
      if (typeof validator.json === "object" && validator.json !== null) return validator.json;
      if (typeof validator.export === "function") {
        try {
          const exp = validator.export();
          return typeof exp === "string" ? JSON.parse(exp) : exp;
        } catch {
          /* fall through */
        }
      }
      return { type: "any" };
  }
}

// ---------------------------------------------------------------------------
// Schema extraction
// ---------------------------------------------------------------------------

async function loadSchemaTables(dir) {
  // Look for schema.{ts,js,mjs} at the root of the convex dir.
  const candidates = ["schema.ts", "schema.js", "schema.mjs"]
    .map((f) => join(dir, f))
    .filter((p) => existsSync(p));
  if (candidates.length === 0) return [];

  const schemaPath = candidates[0];
  const ext = extname(schemaPath);
  let mod;
  try {
    mod = await importModule(schemaPath, ext);
  } catch (err) {
    console.error(`[convex-to-pydantic] Failed to import schema: ${err.message}`);
    return [];
  }
  const schema = mod.default ?? mod.schema ?? null;
  if (!schema) return [];

  // Preferred: SchemaDefinition.export() returns a JSON string with tables
  // already in canonical form. This is Convex's own serialization path.
  if (typeof schema.export === "function") {
    try {
      const exported = schema.export();
      const parsed = typeof exported === "string" ? JSON.parse(exported) : exported;
      if (parsed && Array.isArray(parsed.tables)) {
        return parsed.tables.map((t) => ({
          tableName: t.tableName,
          indexes: t.indexes || [],
          documentType: t.documentType,
        }));
      }
    } catch (err) {
      console.error(`[convex-to-pydantic] schema.export() failed: ${err.message}`);
    }
  }

  // Fallback: walk schema.tables directly. (Older Convex shapes.)
  if (schema.tables && typeof schema.tables === "object") {
    const tables = [];
    for (const [tableName, tableDef] of Object.entries(schema.tables)) {
      try {
        const docValidator = tableDef.validator || tableDef.documentType;
        if (docValidator) {
          tables.push({
            tableName,
            indexes: tableDef.indexes || [],
            documentType: validatorToJson(docValidator),
          });
        }
      } catch (err) {
        console.error(
          `[convex-to-pydantic] Failed to extract schema for table ${tableName}: ${err.message}`
        );
      }
    }
    return tables;
  }

  return [];
}

// ---------------------------------------------------------------------------
// Function discovery
// ---------------------------------------------------------------------------

async function discoverFunctions(dir) {
  const files = collectModuleFiles(dir);
  const results = [];
  for (const { absPath, modulePath, ext } of files) {
    let mod;
    try {
      mod = await importModule(absPath, ext);
    } catch (err) {
      console.error(`[convex-to-pydantic] Skipping ${modulePath}: ${err.message}`);
      continue;
    }
    for (const [exportName, value] of Object.entries(mod)) {
      if (exportName === "default") continue;
      const type = detectFunctionType(value);
      if (!type) continue;
      if (value.isInternal === true) continue; // parity with api.* walk
      let extractedArgs;
      try {
        extractedArgs = extractArgs(value);
      } catch (err) {
        console.error(
          `[convex-to-pydantic] Failed to extract args for ${modulePath}:${exportName}: ${err.message}`
        );
        extractedArgs = { type: "object", value: {} };
      }
      results.push({
        module: modulePath,
        name: exportName,
        type,
        args: extractedArgs,
      });
    }
  }
  return results;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

const [functions, tables] = await Promise.all([discoverFunctions(convexDir), loadSchemaTables(convexDir)]);

// Deterministic ordering.
functions.sort((a, b) => {
  if (a.module !== b.module) return a.module < b.module ? -1 : 1;
  return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
});
tables.sort((a, b) => (a.tableName < b.tableName ? -1 : a.tableName > b.tableName ? 1 : 0));

if (esbuildLoadFailed) {
  process.stderr.write(
    "[convex-to-pydantic] Fatal: esbuild is not available in your Convex project's " +
      "node_modules. Run `pnpm install` (or `npm install`) in the Convex project root " +
      "before running codegen.\n"
  );
  process.exit(1);
}

if (tables.length === 0 && functions.length === 0) {
  process.stderr.write(
    "[convex-to-pydantic] Warning: extraction produced no tables and no functions. " +
      "If your Convex project is genuinely empty this is expected. Otherwise, check " +
      "that your schema and function files are in the directory passed to --convex-dir.\n"
  );
}

console.log(JSON.stringify({ tables, functions }, null, 2));
