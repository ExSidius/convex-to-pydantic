# convex-to-pydantic

Generate fully-typed Pydantic models and async client wrappers from your [Convex](https://convex.dev) schema — automatically, with zero manual wiring.

```
convex-to-pydantic generate --convex-dir ./convex --output-dir ./src/myapp/convex_generated
```

Your IDE immediately gets autocomplete, type checking, and inline docs for every Convex function.

## Requirements

- **Python >= 3.11**
- **Node.js >= 18** (must be on `PATH` — used once per run to introspect your Convex schema)

## Installation

```bash
# with uv (recommended)
uv add convex-to-pydantic

# with pip
pip install convex-to-pydantic
```

### Install from GitHub (pre-release / testing)

While the package is still in development, you can install directly from GitHub:

```bash
# Add as a project dependency
uv add git+https://github.com/ExSidius/convex-to-pydantic.git

# Pin to a specific branch
uv add git+https://github.com/ExSidius/convex-to-pydantic.git@main

# Install as a CLI tool (globally)
uv tool install git+https://github.com/ExSidius/convex-to-pydantic.git

# Or with pip
pip install git+https://github.com/ExSidius/convex-to-pydantic.git
```

## Quick start

### 1. Generate types

```bash
convex-to-pydantic generate \
  --convex-dir ./convex \
  --output-dir ./src/myapp/convex_generated
```

This produces two files in `./src/myapp/convex_generated/`:

| File | Contents |
|------|----------|
| `_types.py` | Pydantic `BaseModel` classes for every table and function argument, plus keyword-arg constructor functions |
| `_client.py` | Async wrapper functions that validate args and call `ConvexClient` methods |

### 2. Use in your code

```python
from myapp.convex_generated._types import messages_send_mutation
from myapp.convex_generated._client import messages_send_mutation_call

# Option 1: Just validate args (e.g. for tests)
args = messages_send_mutation(body="Hello!", author="Alice")

# Option 2: Full async call with validation
result = await messages_send_mutation_call(client, body="Hello!", author="Alice")
```

### 3. Watch mode (for development)

```bash
convex-to-pydantic watch \
  --convex-dir ./convex \
  --output-dir ./src/myapp/convex_generated
```

Run this alongside `npx convex dev`. When your Convex schema changes, types regenerate automatically. See [Watch mode](#watch-mode) for details on how this stays efficient.

## What gets generated

Given a Convex schema with a `messages` table and `messages:send` mutation:

**`_types.py`**

```python
class MessagesTable(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    id_: str = Field(alias="_id")
    creation_time: float = Field(alias="_creationTime")
    author: str
    body: str

class MessagesSendMutationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    body: str
    author: str

def messages_send_mutation(*, body: str, author: str) -> MessagesSendMutationArgs:
    """Validate args for Convex mutation messages:send."""
    return MessagesSendMutationArgs(body=body, author=author)
```

**`_client.py`**

```python
async def messages_send_mutation_call(
    client: "ConvexClient",
    *,
    body: str,
    author: str,
) -> Any:
    """Convex mutation: messages:send"""
    args = messages_send_mutation(body=body, author=author)
    return await client.mutation("messages:send", args.model_dump(by_alias=True, exclude_none=True))
```

## CLI reference

### `generate`

```
convex-to-pydantic generate [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--convex-dir PATH` | Path to your Convex directory (contains `_generated/api.js`). |
| `--input PATH` | Path to a pre-exported JSON file (alternative to `--convex-dir`). |
| `--output-dir PATH` | **(required)** Directory to write `_types.py` and `_client.py`. |
| `--force / -f` | Regenerate even if the schema hasn't changed. |

Either `--convex-dir` or `--input` must be provided. Use `--input` for CI workflows or when you've pre-exported the schema JSON.

### `watch`

```
convex-to-pydantic watch [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--convex-dir PATH` | **(required)** Path to your Convex directory. |
| `--output-dir PATH` | **(required)** Directory to write generated files. |

## Watch mode

Watch mode is designed to run alongside `npx convex dev` during development. Here's how it handles the realities of a live development environment:

### What happens on a file change

```
1. Filesystem event (inotify/FSEvents, not polling)
       │
2. Debounce: 500ms quiet window
   (rapid saves collapse into one check)
       │
3. Source-file hash check
   SHA-256 of all .ts/.js/.mjs file contents
   ┌─ Unchanged? → STOP. No Node.js call.
   │
4. Node.js extraction (single subprocess)
   schema_export.mjs → JSON blob
       │
5. Blob hash check
   SHA-256 of canonical JSON
   ┌─ Unchanged? → STOP. No codegen.
   │  (source changed but schema didn't,
   │   e.g. comment edits, formatting)
   │
6. Pure transform: JSON → IR → _types.py + _client.py
       │
7. Write files + update .convex_codegen_hash
```

### Two-layer staleness detection

The hash file (`.convex_codegen_hash`) stores two lines:

1. **Source-file hash** — SHA-256 over all `.ts/.js/.mjs` file contents in the convex directory. Checked *before* calling Node.js. This is the fast path: if you save a file without changing anything (or edit a non-schema file), we never even spawn Node.
2. **Blob hash** — SHA-256 over the canonical extraction JSON. Checked *after* extraction. Catches cases where source files changed but the schema didn't (comments, formatting, non-schema code).

This means:
- **Editor auto-save** with no changes → stopped at layer 1 (no Node.js)
- **Editing comments** in a Convex file → stopped at layer 2 (Node.js runs, but no codegen)
- **Actual schema change** → full regeneration (~200ms for typical projects)
- **`npx convex dev` writing intermediates** → stopped at layer 1 or 2

### What watch mode does NOT do

- No polling — uses OS-native filesystem events (inotify on Linux, FSEvents on macOS, ReadDirectoryChangesW on Windows)
- No periodic timers — the debounce timer only runs when a filesystem event actually occurs
- No file diffing — hashing is cheaper and more reliable than line-by-line comparison
- No hot reload — it generates static `.py` files. Your IDE/type checker picks up the changes via its own file watcher.

## Supported Convex types

| Convex type | Python type | Notes |
|-------------|-------------|-------|
| `v.string()` | `str` | |
| `v.number()` / `v.float64()` | `float` | JSON wire: `"number"` |
| `v.int64()` | `int` | JSON wire: `"bigint"`. Inline `# int64` comment |
| `v.boolean()` | `bool` | |
| `v.null()` | `None` | |
| `v.bytes()` | `bytes` | |
| `v.any()` | `Any` | |
| `v.id("table")` | `str` | Inline `# Id[table]` comment |
| `v.literal("x")` | `Literal["x"]` | |
| `v.array(T)` | `list[T]` | Nested arrays supported |
| `v.record(K, V)` | `dict[K, V]` | |
| `v.object({...})` | Named `BaseModel` subclass | Nested objects get their own class |
| `v.union(A, B)` | `A \| B` | |
| `v.union(T, v.null())` | `T \| None` | Null-simplified |
| `v.optional(T)` | `T \| None = None` | Default `None` |
| `v.union(v.literal("a"), v.literal("b"))` | `StrEnum` subclass | All-string-literal unions → enum |

> **Note on the Convex JSON spec:** Convex does not publish a formal spec for `ValidatorJSON`. The canonical definition lives in [`get-convex/convex-js/src/values/validators.ts`](https://github.com/get-convex/convex-js/blob/main/src/values/validators.ts). Key gotcha: the JSON wire format uses `"number"` (not `"float64"`) and `"bigint"` (not `"int64"`) — legacy naming from the server. This tool handles both forms.

### System fields

All table models automatically include:

- `id_: str = Field(alias="_id")` — document ID
- `creation_time: float = Field(alias="_creationTime")` — creation timestamp

These are excluded from table constructor functions (since Convex manages them).

## Architecture

```
src/convex_to_pydantic/
├── __init__.py           # Public API: generate(), generate_from_json()
├── pipeline.py           # Pure core: transform(blob) → GeneratedFiles
├── types.py              # Frozen Pydantic IR (immutable discriminated unions)
├── converter.py          # Raw JSON dict → IR (pure)
├── namer.py              # Collision-free naming → NameRegistry (pure)
├── hasher.py             # SHA-256 staleness detection
├── codegen/
│   ├── types_file.py     # IR + NameRegistry → _types.py string (pure)
│   └── client_file.py    # IR + NameRegistry → _client.py string (pure)
├── extractor/
│   ├── runner.py          # Node.js subprocess wrapper (IO edge)
│   └── schema_export.mjs  # Bundled JS: auto-discovers via _generated/api.js
├── watcher.py             # Debounced watchdog file monitor (IO edge)
└── cli.py                 # Typer CLI (IO edge)
```

### Pure functional core

The entire transformation pipeline is a single pure function:

```python
from convex_to_pydantic.pipeline import transform

result = transform(blob)  # dict → GeneratedFiles (frozen dataclass)
result.types_content      # str — the _types.py file
result.client_content     # str — the _client.py file
```

No IO, no mutation, no side effects. The IR models are frozen (immutable), the namer returns a `NameRegistry` instead of mutating, and codegen produces strings. All side effects (file reads, subprocess calls, file writes) live exclusively at the edges: `cli.py`, `__init__.py`, and `runner.py`.

This means:
- **Testing is trivial** — pass a dict, assert on strings. No mocking.
- **Deterministic** — same input always produces identical output.
- **Debuggable** — inspect the IR and NameRegistry at any point without worrying about mutation order.

### Module auto-discovery

The bundled `schema_export.mjs` walks the API object exported by `_generated/api.js` at runtime. No hard-coded `CONVEX_MODULES` list — when you add a new Convex function, it's picked up automatically.

## Programmatic API

```python
from pathlib import Path
from convex_to_pydantic import generate, generate_from_json

# From a live Convex project (requires Node.js)
generate(
    convex_dir=Path("./convex"),
    output_dir=Path("./src/myapp/convex_generated"),
)

# From a pre-exported JSON file (no Node.js needed)
generate_from_json(
    input_json=Path("./schema_export.json"),
    output_dir=Path("./src/myapp/convex_generated"),
)
```

For lower-level access to the pure pipeline:

```python
import json
from convex_to_pydantic.pipeline import transform

blob = json.loads(Path("schema.json").read_text())
result = transform(blob)
print(result.types_content)   # the _types.py source
print(result.client_content)  # the _client.py source
print(result.num_tables, result.num_functions)
```

## Code quality guidelines

This project follows a few conventions to keep the codebase clean and predictable:

1. **Pure functional core.** The entire transformation pipeline (`converter.py` → `namer.py` → `codegen/`) is pure — no IO, no mutation, no side effects. All IR models are frozen/immutable. Side effects live exclusively at the edges: `cli.py`, `__init__.py`, `runner.py`.

2. **Guard clauses over nesting.** Functions use early returns to handle edge cases at the top, keeping the main logic at a single indentation level. Avoid deep `if/elif/else` chains.

3. **No blanket exception catching.** Catch specific exception types (`OSError`, `json.JSONDecodeError`, `ValueError`, etc.), never bare `except Exception`.

4. **Focused, typed functions.** Every function has a clear input/output contract. No hidden state, no global mutation. Type annotations on all public APIs.

5. **No speculative abstractions.** Don't add helpers, utilities, or configurability for hypothetical future needs. Three similar lines of code is better than a premature abstraction.

## Development

```bash
# Clone and install
git clone https://github.com/ExSidius/convex-to-pydantic.git
cd convex-to-pydantic
uv sync

# Run tests (113 tests, ~0.3s)
uv run pytest

# Lint + format
uv run ruff check .
uv run ruff format .

# Type check
uv run pyright
```

### Pre-commit hooks (prek)

This project uses [prek](https://prek.j178.dev/) for pre-commit hooks. To set up:

```bash
# Install prek
uv tool install prek
# or: brew install prek

# Install git hooks
prek install

# Run hooks manually
prek run --all-files
```

Configured hooks (see `.pre-commit-config.yaml`):
- **ruff check** — lint with auto-fix
- **ruff format** — code formatting
- **pyright** — type checking
- **biome check** — JS/TS linting and formatting

### Test fixtures

Tests use four JSON fixtures covering all type variants:

| Fixture | Covers |
|---------|--------|
| `chat_app.json` | Basic strings, empty args, simple mutations/queries |
| `auth_app.json` | `v.id()`, `v.optional()`, `v.union()` with null, string-literal unions (→ StrEnum) |
| `ai_app.json` | `v.array()`, nullable ID pattern |
| `kitchen_sink.json` | `v.int64()`, `v.record()`, `v.bytes()`, nested objects (2 levels), non-string literals, mixed literal+null union, nested arrays, empty args, actions |

## License

MIT
