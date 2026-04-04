#!/usr/bin/env node
/**
 * Convex schema extractor.
 *
 * Auto-discovers all modules from _generated/api.js and exports
 * table schemas + function argument schemas as a single JSON blob.
 *
 * Usage:
 *   node schema_export.mjs --convex-dir ./convex
 */

import { createRequire } from "module";
import { resolve, join } from "path";
import { existsSync } from "fs";

// Parse args
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

const require = createRequire(join(convexDir, "node_modules", ".package.json"));

// ---------------------------------------------------------------------------
// Load the Convex API object
// ---------------------------------------------------------------------------

const apiPath = join(convexDir, "_generated", "api.js");
if (!existsSync(apiPath)) {
  console.error(`Error: ${apiPath} not found. Run 'npx convex dev' first.`);
  process.exit(1);
}

let api;
try {
  const apiModule = await import(`file://${apiPath}`);
  api = apiModule.api || apiModule.default?.api;
} catch (e) {
  console.error(`Failed to load ${apiPath}: ${e.message}`);
  process.exit(1);
}

if (!api) {
  console.error("Could not find 'api' export in _generated/api.js");
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Load schema if available
// ---------------------------------------------------------------------------

let schemaModule = null;
const schemaPath = join(convexDir, "_generated", "api.js")
  .replace("api.js", "server.js");

// Try loading schema.ts compiled output
try {
  const schemaTsPath = join(convexDir, "schema.ts");
  if (existsSync(schemaTsPath)) {
    // The schema is typically available via the generated dataModel
    const serverModule = await import(`file://${join(convexDir, "_generated", "server.js")}`);
    schemaModule = serverModule;
  }
} catch (_) {
  // Schema loading is best-effort
}

// ---------------------------------------------------------------------------
// Discover modules and functions from API object
// ---------------------------------------------------------------------------

function walkApi(obj, prefix = "") {
  const results = [];
  if (!obj || typeof obj !== "object") return results;

  for (const [key, value] of Object.entries(obj)) {
    if (key.startsWith("_")) continue;

    const modulePath = prefix ? `${prefix}/${key}` : key;

    // Check if this looks like a function reference (has properties like _name, _argsValidator, etc.)
    if (value && typeof value === "object") {
      // Convex function references have specific internal properties
      const fnType = value._type;
      if (fnType && ["query", "mutation", "action"].includes(fnType)) {
        results.push({
          module: prefix || key,
          name: prefix ? key : key,
          fullPath: modulePath,
          ref: value,
          type: fnType,
        });
      } else {
        // Recurse into module namespace
        results.push(...walkApi(value, modulePath));
      }
    }
  }
  return results;
}

const discovered = walkApi(api);

// ---------------------------------------------------------------------------
// Extract argument validators
// ---------------------------------------------------------------------------

function validatorToJson(validator) {
  if (!validator) return { type: "any" };

  // Handle the Convex validator format
  if (typeof validator !== "object") return { type: "any" };

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
      return {
        type: "array",
        value: validatorToJson(validator.element || validator.value),
      };
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
    case "object":
      const fields = {};
      const fieldMap = validator.fields || validator.value || {};
      for (const [name, fieldValidator] of Object.entries(fieldMap)) {
        if (fieldValidator && typeof fieldValidator === "object") {
          // Handle {fieldType, optional} or direct validator
          if ("fieldType" in fieldValidator) {
            fields[name] = {
              fieldType: validatorToJson(fieldValidator.fieldType),
              optional: fieldValidator.optional || false,
            };
          } else if ("kind" in fieldValidator || "type" in fieldValidator) {
            fields[name] = {
              fieldType: validatorToJson(fieldValidator),
              optional: fieldValidator.isOptional || false,
            };
          } else {
            fields[name] = {
              fieldType: validatorToJson(fieldValidator),
              optional: false,
            };
          }
        }
      }
      return { type: "object", value: fields };
    default:
      // Try to handle validators with json() method
      if (typeof validator.json === "function") {
        return validator.json();
      }
      // Try export method
      if (typeof validator.export === "function") {
        return validator.export();
      }
      return { type: "any" };
  }
}

// ---------------------------------------------------------------------------
// Extract tables from schema
// ---------------------------------------------------------------------------

const tables = [];

// Try to get table schemas from the schema definition
try {
  const schemaPath2 = join(convexDir, "schema.js");
  const schemaTsPath = join(convexDir, "schema.ts");

  // Try loading the compiled schema
  let schemaObj = null;
  for (const path of [schemaPath2]) {
    if (existsSync(path)) {
      try {
        const mod = await import(`file://${path}`);
        schemaObj = mod.default || mod;
        break;
      } catch (_) {}
    }
  }

  if (schemaObj && schemaObj.tables) {
    for (const [tableName, tableDef] of Object.entries(schemaObj.tables)) {
      try {
        const docValidator = tableDef.validator || tableDef.documentType;
        if (docValidator) {
          tables.push({
            tableName,
            indexes: [],
            documentType: validatorToJson(docValidator),
          });
        }
      } catch (e) {
        console.error(`Warning: Failed to extract schema for table ${tableName}: ${e.message}`);
      }
    }
  }
} catch (_) {
  // Schema extraction is best-effort
}

// ---------------------------------------------------------------------------
// Build function list
// ---------------------------------------------------------------------------

const functions = [];

for (const fn of discovered) {
  const entry = {
    module: fn.module,
    name: fn.name,
    type: fn.type,
    args: { type: "object", value: {} },
  };

  try {
    const argsValidator = fn.ref._argsValidator || fn.ref.argsValidator;
    if (argsValidator) {
      if (typeof argsValidator.json === "function") {
        entry.args = argsValidator.json();
      } else if (typeof argsValidator.export === "function") {
        entry.args = argsValidator.export();
      } else {
        entry.args = validatorToJson(argsValidator);
      }
    }
  } catch (e) {
    console.error(`Warning: Failed to extract args for ${fn.module}:${fn.name}: ${e.message}`);
  }

  functions.push(entry);
}

// ---------------------------------------------------------------------------
// Output
// ---------------------------------------------------------------------------

const output = { tables, functions };
console.log(JSON.stringify(output, null, 2));
