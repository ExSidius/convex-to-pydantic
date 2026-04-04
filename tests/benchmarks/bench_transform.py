"""Benchmark suite for the pure Python transform pipeline.

Usage:
    python -m tests.benchmarks.bench_transform

Reports per-stage and end-to-end timings with median, p95, p99.
No external dependencies required.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from convex_to_pydantic.codegen.client_file import generate_client_file
from convex_to_pydantic.codegen.types_file import generate_types_file
from convex_to_pydantic.converter import parse_export
from convex_to_pydantic.hasher import blob_hash
from convex_to_pydantic.namer import assign_names
from convex_to_pydantic.pipeline import transform

FIXTURES = Path(__file__).parent.parent / "fixtures"
LARGE_FIXTURE = FIXTURES / "large_export.json"
ITERATIONS = 20


def _bench(fn, *, iterations: int = ITERATIONS) -> list[float]:
    """Run fn repeatedly, return list of durations in ms."""
    # Warmup
    fn()
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return times


def _report(name: str, times: list[float]) -> None:
    """Print a single benchmark row."""
    med = statistics.median(times)
    p95 = sorted(times)[int(len(times) * 0.95)]
    p99 = sorted(times)[int(len(times) * 0.99)]
    mn = min(times)
    print(f"  {name:<30s}  {med:>8.2f}ms  {p95:>8.2f}ms  {p99:>8.2f}ms  {mn:>8.2f}ms")


def main() -> None:
    blob = json.loads(LARGE_FIXTURE.read_text())
    num_tables = len(blob["tables"])
    num_functions = len(blob["functions"])
    print(f"Benchmark: {num_tables} tables, {num_functions} functions, {ITERATIONS} iterations\n")

    print(f"  {'Stage':<30s}  {'median':>8s}    {'p95':>8s}    {'p99':>8s}    {'min':>8s}")
    print(f"  {'-' * 30}  {'-' * 8}    {'-' * 8}    {'-' * 8}    {'-' * 8}")

    # Stage 1: parse_export
    times_parse = _bench(lambda: parse_export(blob))
    _report("parse_export", times_parse)

    # Stage 2: assign_names (needs parsed export)
    export = parse_export(blob)
    times_names = _bench(lambda: assign_names(export))
    _report("assign_names", times_names)

    # Stage 3: codegen (needs export + names)
    names_reg = assign_names(export)
    times_types = _bench(lambda: generate_types_file(export, names_reg))
    _report("generate_types_file", times_types)

    times_client = _bench(lambda: generate_client_file(export, names_reg))
    _report("generate_client_file", times_client)

    # Stage 4: blob_hash
    times_hash = _bench(lambda: blob_hash(blob))
    _report("blob_hash", times_hash)

    # End-to-end: full transform
    times_total = _bench(lambda: transform(blob))
    _report("transform (end-to-end)", times_total)

    print()

    # Output size
    result = transform(blob)
    types_kb = len(result.types_content.encode()) / 1024
    client_kb = len(result.client_content.encode()) / 1024
    print(f"Output: _types.py = {types_kb:.1f}KB, _client.py = {client_kb:.1f}KB")
    print(f"        {result.num_tables} tables, {result.num_functions} functions")

    total_med = statistics.median(times_total)
    if total_med < 200:
        print(f"\nResult: PASS — transform median {total_med:.1f}ms (target <200ms)")
    else:
        print(f"\nResult: SLOW — transform median {total_med:.1f}ms (target <200ms)")

    # Also benchmark smaller realistic sizes
    print("\n--- Scaling across sizes ---\n")
    print(f"  {'Size':<30s}  {'median':>8s}    {'min':>8s}")
    print(f"  {'-' * 30}  {'-' * 8}    {'-' * 8}")

    from tests.benchmarks.generate_large_fixture import generate as gen_fixture

    for n_tables, n_fns in [(5, 20), (30, 150), (100, 500)]:
        b = gen_fixture(n_tables, n_fns)
        ts = _bench(lambda b=b: transform(b), iterations=15)
        med = statistics.median(ts)
        mn = min(ts)
        print(f"  {n_tables} tables + {n_fns} functions{'':<10s}  {med:>8.2f}ms  {mn:>8.2f}ms")


if __name__ == "__main__":
    main()
