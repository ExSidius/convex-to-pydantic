"""Shared pytest fixtures for extractor tests.

Two kinds of tests live alongside this conftest:

1. Pure-Python tests (pipeline, converter, codegen, etc.) — these don't touch
   the filesystem beyond the JSON fixtures under ``tests/fixtures/*.json`` and
   don't need anything here.

2. Extractor subprocess tests (``test_extractor.py``) — these invoke the
   bundled Node.js extractor against real Convex projects under
   ``tests/fixtures/convex_projects/``. Some need only ``pnpm install`` (to
   make ``convex`` resolvable from the fixture's ``node_modules``); others
   additionally need a running self-hosted Convex backend (Docker) to produce
   a concrete ``_generated/api.js``. Fixtures in this file provide both.

Availability helpers auto-skip tests when their prerequisites aren't present,
so running ``pytest`` on a developer machine without Docker still exercises
the no-docker tests.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import socket
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from convex_to_pydantic.extractor.runner import extract

TESTS_DIR = Path(__file__).parent
FIXTURES_DIR = TESTS_DIR / "fixtures" / "convex_projects"
COMPOSE_FILE = TESTS_DIR / "docker-compose.yml"

# Filename used by the conftest to preserve the pristine pre-deploy
# ``_generated/api.js`` (the ``anyApi`` stub) before ``convex deploy``
# overwrites it with the concrete api. Tests can swap it back in via
# ``with_anyapi_stub`` to exercise the "user never ran convex dev" scenario.
ANYAPI_STUB_BACKUP = "api.anyapi-stub.js"


# ---------------------------------------------------------------------------
# Availability checks
# ---------------------------------------------------------------------------


def _has_cli(name: str) -> bool:
    return shutil.which(name) is not None


def _docker_compose_available() -> bool:
    """Is ``docker compose`` usable (binary on PATH + daemon running)?"""
    if not _has_cli("docker"):
        return False
    try:
        res = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode != 0:
            return False
    except (OSError, subprocess.TimeoutExpired):
        return False
    # Daemon has to be running, not just the CLI installed.
    try:
        res = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return res.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


HAS_PNPM = _has_cli("pnpm")
HAS_NODE = _has_cli("node")
HAS_DOCKER_COMPOSE = _docker_compose_available()


# ---------------------------------------------------------------------------
# Marker-based auto-skipping
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests marked ``requires_docker`` / ``requires_pnpm`` when the
    corresponding tooling isn't on PATH. Keeps the test suite runnable in
    minimal CI environments without hiding intent: the markers are the
    source of truth.
    """
    skip_docker = pytest.mark.skip(
        reason="docker + docker compose with a running daemon not available"
    )
    skip_pnpm = pytest.mark.skip(reason="pnpm not available on PATH")
    skip_node = pytest.mark.skip(reason="node not available on PATH")
    for item in items:
        if "requires_docker" in item.keywords and not HAS_DOCKER_COMPOSE:
            item.add_marker(skip_docker)
        if "requires_pnpm" in item.keywords and not HAS_PNPM:
            item.add_marker(skip_pnpm)
        # Every extractor test ultimately spawns node; skip early with a
        # clearer message if it's missing.
        if (
            "requires_pnpm" in item.keywords or "requires_docker" in item.keywords
        ) and not HAS_NODE:
            item.add_marker(skip_node)


# ---------------------------------------------------------------------------
# Fixture path helpers
# ---------------------------------------------------------------------------


def _fixture_path(name: str) -> Path:
    p = FIXTURES_DIR / name
    if not p.exists():
        raise FileNotFoundError(f"Unknown Convex test fixture: {name} (looked at {p})")
    return p


def _pnpm_install(fixture_dir: Path) -> None:
    """Install node_modules for a fixture. Idempotent: skips when the
    top-level ``convex`` package is already present (stat-based cache)."""
    convex_pkg = fixture_dir / "node_modules" / "convex" / "package.json"
    if convex_pkg.exists():
        return
    if not HAS_PNPM:
        pytest.skip("pnpm not available on PATH")
    # Some fixtures might not have a lockfile yet; ``pnpm install`` creates
    # one without needing ``--frozen-lockfile``. Prefer frozen when present
    # for reproducibility.
    has_lock = (fixture_dir / "pnpm-lock.yaml").exists()
    cmd = ["pnpm", "install"]
    if has_lock:
        cmd.append("--frozen-lockfile")
    subprocess.run(cmd, cwd=fixture_dir, check=True, capture_output=True, text=True)


def _save_anyapi_stub(fixture_dir: Path) -> Path:
    """Back up the pre-deploy ``_generated/api.js`` so tests can swap it
    back in later via ``with_anyapi_stub``."""
    api_js = fixture_dir / "convex" / "_generated" / "api.js"
    backup = fixture_dir / "convex" / "_generated" / ANYAPI_STUB_BACKUP
    if not backup.exists() and api_js.exists():
        shutil.copy2(api_js, backup)
    return backup


# ---------------------------------------------------------------------------
# Self-hosted Convex backend (session-scoped)
# ---------------------------------------------------------------------------


def _wait_for_port(host: str, port: int, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                return
        except OSError as e:
            last_err = e
            time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for {host}:{port} — last: {last_err!r}")


def _compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _resolve_host_port(service: str, container_port: int) -> int:
    res = _compose("port", service, str(container_port))
    # Output is like "0.0.0.0:49183\n"; take the tail after the last colon.
    line = res.stdout.strip().splitlines()[-1]
    return int(line.rsplit(":", 1)[-1])


def _generate_admin_key(deployment: str) -> str:
    """Ask the backend container to mint an admin key for our deployment."""
    res = _compose(
        "exec",
        "-T",
        "convex-backend",
        "./generate_admin_key.sh",
        deployment,
    )
    # The script prints the key on the last non-empty line.
    for line in reversed(res.stdout.splitlines()):
        line = line.strip()
        if line:
            return line
    raise RuntimeError(
        f"Could not parse admin key from generate_admin_key.sh output: {res.stdout!r}"
    )


@pytest.fixture(scope="session")
def convex_backend() -> Iterator[tuple[str, str]]:
    """Session-scoped self-hosted Convex backend.

    Yields ``(url, admin_key)`` pointed at a locally running convex-backend
    Docker container. Skipped automatically if Docker isn't available.
    """
    if not HAS_DOCKER_COMPOSE:
        pytest.skip("docker + docker compose with a running daemon not available")

    _compose("up", "-d", "--wait")
    try:
        http_port = _resolve_host_port("convex-backend", 3210)
        _wait_for_port("127.0.0.1", http_port, timeout=90)
        url = f"http://127.0.0.1:{http_port}"
        admin_key = _generate_admin_key("c2p-tests")
        yield (url, admin_key)
    finally:
        # ``down -v`` tears the volume too so data doesn't leak across
        # sessions. The container is cheap to spin up.
        _compose("down", "-v", check=False)


# ---------------------------------------------------------------------------
# Deployed fixture factory
# ---------------------------------------------------------------------------


DeployedFixtureFactory = Callable[[str], Path]


@pytest.fixture(scope="session")
def deployed_fixture(convex_backend) -> DeployedFixtureFactory:
    """Factory: ``deployed_fixture("basic") -> Path`` gives a fixture dir
    whose ``convex/_generated/api.js`` is the real post-deploy concrete
    api, with the pre-deploy stub preserved at
    ``convex/_generated/api.anyapi-stub.js``.

    Session-scoped: each fixture is deployed at most once per session.
    """
    url, admin_key = convex_backend
    deployed: dict[str, Path] = {}

    def _deploy(name: str) -> Path:
        if name in deployed:
            return deployed[name]
        fixture_dir = _fixture_path(name)
        _pnpm_install(fixture_dir)
        _save_anyapi_stub(fixture_dir)
        env = {
            **os.environ,
            "CONVEX_SELF_HOSTED_URL": url,
            "CONVEX_SELF_HOSTED_ADMIN_KEY": admin_key,
        }
        # ``convex deploy --yes`` skips interactive confirmation. The
        # self-hosted env vars pin us to the local backend.
        subprocess.run(
            ["pnpm", "exec", "convex", "deploy", "--yes"],
            cwd=fixture_dir,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        deployed[name] = fixture_dir
        return fixture_dir

    return _deploy


# ---------------------------------------------------------------------------
# No-docker helpers (pnpm install only; stub api.js stays in place)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def prepared_fixture() -> Callable[[str], Path]:
    """Factory: returns a fixture dir with ``node_modules`` installed but
    WITHOUT having run ``convex deploy``. ``convex/_generated/api.js`` is
    still the ``anyApi`` stub — exactly the bug condition we're fixing.

    This fixture is docker-free, so tests built on it run in any env that
    has node + pnpm.
    """
    prepared: dict[str, Path] = {}

    def _prepare(name: str) -> Path:
        if name in prepared:
            return prepared[name]
        fixture_dir = _fixture_path(name)
        _pnpm_install(fixture_dir)
        prepared[name] = fixture_dir
        return fixture_dir

    return _prepare


# ---------------------------------------------------------------------------
# Extractor runner + anyApi-stub swap
# ---------------------------------------------------------------------------


@pytest.fixture
def run_extractor() -> Callable[[Path], dict]:
    """Invoke the real bundled extractor on a fixture's convex dir and
    return the parsed JSON dict."""

    def _run(fixture_dir: Path) -> dict:
        return extract(fixture_dir / "convex")

    return _run


@pytest.fixture
def run_extractor_raw():
    """Run the extractor as a subprocess and return the full
    ``CompletedProcess`` (stdout / stderr / returncode). Useful for tests
    that need to assert on warnings printed to stderr.
    """
    node = shutil.which("node") or "node"
    script = (
        Path(__file__).parent.parent
        / "src"
        / "convex_to_pydantic"
        / "extractor"
        / "schema_export.mjs"
    )

    def _run(fixture_dir: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [node, str(script), "--convex-dir", str(fixture_dir / "convex")],
            capture_output=True,
            text=True,
            check=False,
        )

    return _run


@contextlib.contextmanager
def _swap_api_js(fixture_dir: Path, stub: Path) -> Iterator[None]:
    """Temporarily swap ``_generated/api.js`` with the saved anyApi stub,
    restoring the concrete file on exit."""
    api_js = fixture_dir / "convex" / "_generated" / "api.js"
    if not stub.exists():
        raise FileNotFoundError(
            f"No anyApi-stub backup found at {stub}. Deploy the fixture first so "
            f"conftest can preserve the original stub."
        )
    concrete_backup = api_js.with_suffix(".concrete.bak")
    if api_js.exists():
        shutil.move(api_js, concrete_backup)
    shutil.copy2(stub, api_js)
    try:
        yield
    finally:
        if api_js.exists():
            api_js.unlink()
        if concrete_backup.exists():
            shutil.move(concrete_backup, api_js)


@pytest.fixture
def with_anyapi_stub():
    """Context manager: swap in the pre-deploy ``anyApi`` stub for the
    duration of a ``with`` block.

    Usage:
        with with_anyapi_stub(fixture_dir):
            result = run_extractor(fixture_dir)
    """

    def _cm(fixture_dir: Path):
        stub = fixture_dir / "convex" / "_generated" / ANYAPI_STUB_BACKUP
        return _swap_api_js(fixture_dir, stub)

    return _cm


# ---------------------------------------------------------------------------
# Small conveniences for assertions
# ---------------------------------------------------------------------------


def _fn_key(entry: dict) -> tuple[str, str]:
    return (entry["module"], entry["name"])


def _fn_keys(blob: dict) -> set[tuple[str, str]]:
    return {_fn_key(f) for f in blob["functions"]}


# Re-export for tests importing from conftest.
__all__ = [
    "FIXTURES_DIR",
    "ANYAPI_STUB_BACKUP",
    "HAS_DOCKER_COMPOSE",
    "HAS_PNPM",
    "HAS_NODE",
]
