"""Generate a large fixture JSON for benchmarking.

Usage:
    python -m tests.benchmarks.generate_large_fixture [--tables N] [--functions N] [--output PATH]

Defaults: 100 tables, 500 functions.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

MODULES = [
    "users",
    "auth",
    "chat/messages",
    "chat/channels",
    "api/v1/posts",
    "api/v1/comments",
    "admin/settings",
    "billing/invoices",
    "billing/subscriptions",
    "analytics/events",
    "analytics/metrics",
    "notifications",
    "files/uploads",
    "files/thumbnails",
    "search/index",
]

FIELD_TYPES = [
    {"type": "string"},
    {"type": "float64"},
    {"type": "boolean"},
    {"type": "int64"},
    {"type": "bytes"},
    {"type": "any"},
]

FN_TYPES = ["query", "mutation", "action"]


def _random_field(depth: int = 0) -> dict:
    """Generate a random field type, with occasional nesting."""
    r = random.random()

    if depth < 2 and r < 0.08:
        # Nested object (2-4 fields)
        return {
            "type": "object",
            "value": {
                f"nested_{i}": {
                    "fieldType": _random_field(depth + 1),
                    "optional": random.random() < 0.2,
                }
                for i in range(random.randint(2, 4))
            },
        }
    if r < 0.15:
        return {"type": "array", "value": random.choice(FIELD_TYPES)}
    if r < 0.22:
        return {
            "type": "union",
            "value": [
                {"type": "literal", "value": random.choice(["active", "inactive", "pending"])},
                {"type": "literal", "value": random.choice(["archived", "deleted", "draft"])},
            ],
        }
    if r < 0.28:
        return {"type": "record", "keys": {"type": "string"}, "values": random.choice(FIELD_TYPES)}
    if r < 0.35:
        return {"type": "id", "tableName": f"table_{random.randint(0, 50)}"}

    return random.choice(FIELD_TYPES)


def _generate_table(idx: int) -> dict:
    """Generate a table schema with 5-20 fields."""
    num_fields = random.randint(5, 20)
    fields = {}
    for i in range(num_fields):
        fields[f"field_{i}"] = {
            "fieldType": _random_field(),
            "optional": random.random() < 0.25,
        }
    return {
        "tableName": f"table_{idx}",
        "indexes": [],
        "documentType": {"type": "object", "value": fields},
    }


def _generate_function(idx: int) -> dict:
    """Generate a function schema with 0-8 args."""
    module = MODULES[idx % len(MODULES)]
    fn_type = FN_TYPES[idx % len(FN_TYPES)]
    num_args = random.randint(0, 8)
    args = {}
    for i in range(num_args):
        args[f"arg_{i}"] = {
            "fieldType": _random_field(),
            "optional": random.random() < 0.3,
        }
    return {
        "module": module,
        "name": f"fn_{idx}",
        "type": fn_type,
        "args": {"type": "object", "value": args},
    }


def generate(num_tables: int = 100, num_functions: int = 500, seed: int = 42) -> dict:
    """Generate a large fixture blob."""
    random.seed(seed)
    return {
        "tables": [_generate_table(i) for i in range(num_tables)],
        "functions": [_generate_function(i) for i in range(num_functions)],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate large benchmark fixture")
    parser.add_argument("--tables", type=int, default=100)
    parser.add_argument("--functions", type=int, default=500)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    blob = generate(args.tables, args.functions)

    if args.output:
        args.output.write_text(json.dumps(blob, indent=2))
        print(f"Wrote {args.output} ({args.tables} tables, {args.functions} functions)")
    else:
        print(json.dumps(blob, indent=2))


if __name__ == "__main__":
    main()
