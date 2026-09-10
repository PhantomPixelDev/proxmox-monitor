import threading

import pytest
from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication

from proxmox_widget.core.runner import AsyncRunner


@pytest.fixture
def runner():
    r = AsyncRunner(name="test-async")
    yield r
    r.stop()


def _pump(app: QApplication, ms: int = 800) -> None:
    QTimer.singleShot(ms, app.quit)
    app.exec()


def test_coroutine_runs_off_the_gui_thread(qapp, runner):
    seen: dict[str, object] = {}

    async def work() -> str:
        return threading.current_thread().name

    runner.submit(
        work,
        lambda r: seen.update(worker=r, gui=QThread.currentThread() == qapp.thread()),
    )
    _pump(qapp)

    assert seen["worker"] == "test-async"
    assert seen["gui"] is True, "callbacks must arrive on the GUI thread"


def test_result_survives_a_dropped_task_reference(qapp, runner):
    """A short coroutine finishes before the caller could connect anything."""
    seen: list[object] = []

    async def instant() -> str:
        return "value"

    runner.submit(instant, seen.append)  # return value deliberately ignored
    _pump(qapp)

    assert seen == ["value"]


def test_failures_reach_the_error_callback(qapp, runner):
    errors: list[BaseException] = []

    async def boom() -> None:
        raise ValueError("nope")

    runner.submit(boom, None, errors.append)
    _pump(qapp)

    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)


def test_gui_stays_responsive_while_a_coroutine_blocks(qapp, runner):
    """The point of the whole class: a slow call must not freeze the window."""
    import asyncio

    ticks = []
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: ticks.append(1))
    heartbeat.start(50)

    async def slow() -> str:
        await asyncio.sleep(1.0)
        return "done"

    done: list[str] = []
    runner.submit(slow, done.append)
    _pump(qapp, 1500)
    heartbeat.stop()

    assert done == ["done"]
    # ~30 ticks in 1.5s; anything above 10 means the loop kept running
    assert len(ticks) > 10, f"event loop stalled, only {len(ticks)} ticks"
