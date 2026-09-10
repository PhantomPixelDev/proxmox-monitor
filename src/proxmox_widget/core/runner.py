"""One asyncio loop on one background thread.

Every Proxmox call used to run through ``asyncio.run`` inside a Qt timer
callback, which is the GUI thread: an unreachable host froze the window for the
whole connect timeout, and a power action froze it for as long as the guest took
to change state. Coroutines now run here instead, and results come back as Qt
signals, which Qt delivers to the GUI thread as queued calls.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from typing import Any

from loguru import logger
from PySide6.QtCore import QObject, Signal


class AsyncTask(QObject):
    """Result carrier for one submitted coroutine.

    Created on the GUI thread, emitted from the worker thread, so connected
    slots that belong to GUI objects run on the GUI thread.
    """

    done = Signal(object)
    failed = Signal(object)


class AsyncRunner:
    def __init__(self, name: str = "proxmox-async") -> None:
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._pending: set[AsyncTask] = set()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.call_soon(self._ready.set)
        self._loop.run_forever()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def submit(
        self,
        factory: Callable[[], Coroutine[Any, Any, Any]],
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
    ) -> AsyncTask:
        """Schedule ``factory()`` on the worker loop and report through the task.

        Callbacks are connected here rather than by the caller afterwards: a
        short coroutine can finish and emit before the caller gets a chance to
        connect, and the result would be dropped.
        """
        task = AsyncTask()
        if on_done is not None:
            task.done.connect(on_done)
        if on_error is not None:
            task.failed.connect(on_error)
        # hold a reference until the result has been delivered: a task the caller
        # drops would be collected and its queued signal never arrive. These
        # connect last, so they run after the caller's own slots.
        self._pending.add(task)
        task.done.connect(lambda _r, t=task: self._pending.discard(t))
        task.failed.connect(lambda _e, t=task: self._pending.discard(t))

        def _schedule() -> None:
            future = asyncio.ensure_future(factory())

            def _finished(f: asyncio.Future[Any]) -> None:
                if f.cancelled():
                    return
                error = f.exception()
                if error is not None:
                    logger.debug("async task failed: {}", error)
                    task.failed.emit(error)
                else:
                    task.done.emit(f.result())

            future.add_done_callback(_finished)

        self._loop.call_soon_threadsafe(_schedule)
        return task

    def stop(self, timeout: float = 2.0) -> None:
        if not self._thread.is_alive():
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=timeout)
