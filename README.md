# convex-to-pydantic

Generate fully-typed Pydantic models and async client wrappers from your [Convex](https://convex.dev) schema — automatically, with zero manual wiring.

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

## Quick start

```bash
# One-shot generation
convex-to-pydantic generate \
  --convex-dir ./convex \
  --output-dir ./src/myapp/convex_generated

# Watch mode — regenerates on schema changes
convex-to-pydantic watch \
  --convex-dir ./convex \
  --output-dir ./src/myapp/convex_generated
```

This produces two files:

| File | Contents |
|------|----------|
| `_types.py` | Pydantic `BaseModel` classes for every table and function argument, plus keyword-arg constructor functions |
| `_client.py` | Async wrapper functions that validate args and call `ConvexClient` methods |

## What you get

Given a Convex schema with a `messages` table and `messages:send` mutation:

### `_types.py`

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

### `_client.py`

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

### Usage in your code

```python
from myapp.convex_generated._types import messages_send_mutation
from myapp.convex_generated._client import messages_send_mutation_call

# Option 1: Just validate args (e.g. for tests)
args = messages_send_mutation(body="Hello!", author="Alice")

# Option 2: Full async call with validation
result = await messages_send_mutation_call(client, body="Hello!", author="Alice")
```

Your IDE gives you autocomplete, type checking, and inline documentation for every Convex function — no manual type stubs required.

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

Either `--convex-dir` or `--input` must be provided. Use `--input` for offline/CI workflows where Node.js extraction has already been done.

### `watch`

```
convex-to-pydantic watch [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--convex-dir PATH` | **(required)** Path to your Convex directory. |
| `--output-dir PATH` | **(required)** Directory to write generated files. |

Watches `*.ts`, `*.js`, `*.mjs`, `*.tsx`, `*.jsx` files recursively. Events are debounced (500ms quiet window) so rapid saves collapse into a single regeneration. A content hash check ensures no work is done unless the schema actually changed.

## How it works

```
Node.js (single subprocess, invoked once per run)
  └─ schema_export.mjs
       ├─ Reads _generated/api.js → discovers all modules automatically
       ├─ Calls exportArgs() for each function
       └─ Emits one JSON blob to stdout

Python pipeline
  └─ extractor/runner.py  → raw dict
  └─ converter.py         → IR (typed Pydantic model tree)
  └─ namer.py             → assigns all class names upfront, collision-free
  └─ codegen/types_file.py  → _types.py string
  └─ codegen/client_file.py → _client.py string
  └─ hasher.py            → SHA-256 content hash for staleness detection
  └─ write files + ruff format (if available)
```

### Staleness detection

The pipeline computes a SHA-256 digest of the canonical extraction JSON and stores it in `.convex_codegen_hash` alongside the generated files. On subsequent runs, if the hash matches, regeneration is skipped entirely. This makes watch mode efficient: filesystem events fire frequently (editor auto-save, `npx convex dev` writing intermediates), but the expensive extraction + codegen only runs when schema content actually changes.

Why a content hash instead of a merkle tree? The extraction output is a single JSON blob, not a tree of independent artifacts. A merkle tree would add complexity without benefit — a flat SHA-256 over the canonical JSON is O(n) in the schema size and more than sufficient.

### Module auto-discovery

Unlike manual approaches that require a hard-coded `CONVEX_MODULES` list, the bundled `schema_export.mjs` walks the API object exported by `_generated/api.js` at runtime. When you add a new Convex function, it's picked up automatically on the next `generate` or `watch` cycle.

## Supported Convex types

| Convex type | Python type | Notes |
|-------------|-------------|-------|
| `v.string()` | `str` | |
| `v.number()` / `v.float64()` | `float` | |
| `v.int64()` | `int` | Inline `# int64` comment |
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

### System fields

All table models automatically include:

- `id_: str = Field(alias="_id")` — document ID
- `creation_time: float = Field(alias="_creationTime")` — creation timestamp

These are excluded from table constructor functions (since Convex manages them).

## Architecture

```
src/convex_to_pydantic/
├── __init__.py                     # Public API: generate(), generate_from_json()
├── types.py                        # Convex type IR — Pydantic discriminated unions
├── converter.py                    # Raw JSON dict → IR
├── namer.py                        # Collision-free PascalCase class naming
├── hasher.py                       # SHA-256 content-hash staleness detection
├── codegen/
│   ├── types_file.py               # IR → _types.py (models + constructors)
│   └── client_file.py              # IR → _client.py (async client wrappers)
├── extractor/
│   ├── runner.py                   # Node.js subprocess wrapper + pre-flight check
│   └── schema_export.mjs           # Bundled JS: auto-discovers via _generated/api.js
├── watcher.py                      # Debounced watchdog file monitor
└── cli.py                          # Typer CLI: generate + watch
```

### Design decisions

- **Single Node.js call** — not per-file. The extractor runs once and returns everything as one JSON blob. This is both faster and more reliable than spawning N subprocesses.
- **Names assigned upfront** — the `Namer` class walks the entire IR and assigns collision-free PascalCase names in a single pass *before* codegen. No post-hoc regex renaming.
- **Topological sort** — nested `BaseModel` classes are emitted leaf-first so forward references aren't needed (though `from __future__ import annotations` is included as a safety net).
- **`model_config = ConfigDict(extra="forbid", populate_by_name=True)`** — strict validation by default. Typos in field names are caught at construction time, not silently ignored.
- **Content-hash skip** — avoids unnecessary file writes, which means downstream tools (file watchers, type checkers, build systems) aren't triggered spuriously.

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

## Development

```bash
# Clone and install
git clone https://github.com/ExSidius/convex-to-pydantic.git
cd convex-to-pydantic
uv sync

# Run tests
uv run pytest

# Lint + format
uv run ruff check .
uv run ruff format .

# Type check
uv run pyright
```

## License

MIT
