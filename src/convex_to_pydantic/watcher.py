"""Watch Convex directory for changes and regenerate on modification.

Uses watchdog for filesystem events with a threading.Timer-based debounce.
The callback fires at most once per debounce window — rapid successive events
(e.g. editor saving multiple files, `npx convex dev` rewriting intermediates)
are collapsed into a single regeneration. The actual regeneration then checks
the content hash, so even if the timer fires, no work is done unless the
schema actually changed.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

_WATCH_EXTENSIONS = frozenset((".ts", ".js", ".mjs", ".tsx", ".jsx"))


class _DebouncedHandler(FileSystemEventHandler):
    """Collapse rapid filesystem events into a single callback invocation."""

    def __init__(self, callback: Callable[[], None], debounce_s: float = 0.5) -> None:
        self._callback = callback
        self._debounce_s = debounce_s
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def _fire(self) -> None:
        self._callback()

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src = str(event.src_path)
        if not any(src.endswith(ext) for ext in _WATCH_EXTENSIONS):
            return

        with self._lock:
            # Cancel any pending timer and start a new one.
            # This means the callback only fires after `debounce_s` seconds
            # of *quiet* — no more events resetting the timer.
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce_s, self._fire)
            self._timer.daemon = True
            self._timer.start()


def watch(convex_dir: Path, callback: Callable[[], None]) -> None:
    """Watch convex_dir for changes and call callback on each (debounced).

    The callback should handle its own error reporting. This function blocks
    until interrupted with Ctrl-C.
    """
    handler = _DebouncedHandler(callback)
    observer = Observer()
    observer.schedule(handler, str(convex_dir), recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
