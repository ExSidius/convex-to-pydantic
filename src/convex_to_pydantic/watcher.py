"""Watch Convex directory for changes and regenerate on modification."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


class _DebouncedHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[], None], debounce_ms: int = 500) -> None:
        self._callback = callback
        self._debounce_s = debounce_ms / 1000
        self._last_trigger = 0.0

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src = str(event.src_path)
        if not (src.endswith(".ts") or src.endswith(".js") or src.endswith(".mjs")):
            return

        now = time.time()
        if now - self._last_trigger < self._debounce_s:
            return
        self._last_trigger = now
        self._callback()


def watch(convex_dir: Path, callback: Callable[[], None]) -> None:
    """Watch convex_dir for changes and call callback on each (debounced)."""
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
