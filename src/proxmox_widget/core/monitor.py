"""Polling monitor — aggregates ClusterHealth for all clusters."""

from __future__ import annotations

import asyncio
from typing import Callable

from loguru import logger
from PySide6.QtCore import QObject, Signal, QTimer

from proxmox_widget.api.client import ProxmoxClient
from proxmox_widget.config.models import ClusterHealth

# Signal payload: list[ClusterHealth]
HealthCallback = Callable[[list[ClusterHealth]], None]


class Monitor(QObject):
    health_updated = Signal(list)  # list[ClusterHealth]
    error_occurred = Signal(str)

    def __init__(self, get_clusters_callable: Callable[[], list], interval_seconds: int = 30) -> None:
        super().__init__()
        self._get_clusters = get_clusters_callable
        self._interval = max(5, interval_seconds)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_async)
        self._last_health: list[ClusterHealth] = []
        self._running = False
        # asyncio loop handling via QTimer + asyncio.ensure_future
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._timer.start(self._interval * 1000)
        self.refresh_async()
        logger.info("Monitor started interval={}s", self._interval)

    def stop(self) -> None:
        self._timer.stop()
        self._running = False

    def set_interval(self, seconds: int) -> None:
        self._interval = max(5, seconds)
        if self._running:
            self._timer.start(self._interval * 1000)
        logger.info("Monitor interval -> {}s", self._interval)

    def refresh_async(self) -> None:
        """Kick off async fetch without blocking UI thread."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        # schedule
        asyncio.ensure_future(self._fetch_all(), loop=loop)
        # ensure loop runs if not already (for non-qasync setups, we use qasync fallback via timer)
        # We use a small helper: if loop not running, run until complete via singleShot
        if not loop.is_running():
            # Run one iteration via QTimer singleShot 0 to avoid blocking
            # Instead run synchronously in thread pool style: create task and pump
            # Simpler: use asyncio.run_coroutine_threadsafe alternative — just create new loop and run
            # For UI thread we offload to asyncio.to_thread style: use QTimer to trigger _fetch_all via asyncio.run
            pass

    async def _fetch_all(self) -> None:
        clusters = self._get_clusters()
        if not clusters:
            self.health_updated.emit([])
            return

        async def _one(c: object) -> ClusterHealth:
            # c is ClusterConfig
            from proxmox_widget.config.models import ClusterConfig as CC

            assert isinstance(c, CC)
            client = ProxmoxClient(c)
            try:
                return await client.fetch_health()
            except Exception as e:
                logger.error("fetch health {}: {}", c.id, e)
                return ClusterHealth(
                    cluster_id=c.id,
                    cluster_name=c.name,
                    online=False,
                    error=str(e),
                )

        results = await asyncio.gather(*[_one(c) for c in clusters])
        health = list(results)
        self._last_health = health
        self.health_updated.emit(health)

    # synchronous convenience for tests / manual refresh
    async def fetch_once(self) -> list[ClusterHealth]:
        clusters = self._get_clusters()
        out: list[ClusterHealth] = []
        for c in clusters:
            client = ProxmoxClient(c)
            try:
                h = await client.fetch_health()
            except Exception as e:
                from proxmox_widget.config.models import ClusterHealth as CH

                h = CH(cluster_id=c.id, cluster_name=c.name, online=False, error=str(e))
            out.append(h)
        return out
