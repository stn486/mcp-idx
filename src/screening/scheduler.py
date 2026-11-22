"""Pemicu refresh snapshot terjadwal: data tertinggal dari tanggal bursa terakhir, atau snapshot terlalu tua."""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from . import engine

logger = logging.getLogger(__name__)

MAX_AGE_DAYS = int(os.environ.get("SCREENING_MAX_AGE_DAYS", "3"))
RETRY_MINUTES = int(os.environ.get("SCREENING_RETRY_MINUTES", "60"))
CHECK_SECONDS = int(os.environ.get("SCREENING_CHECK_SECONDS", "900"))
AUTO_ENABLED = os.environ.get("SCREENING_AUTO_REFRESH", "true").lower() not in ("0", "false", "no")


def should_refresh(snapshot: Optional[dict], now_utc: datetime, freshness: Optional[dict] = None) -> tuple:
    """Keputusan refresh. Fungsi murni: tanpa jaringan."""
    if not snapshot:
        return True, "no_snapshot"
    if snapshot.get("partial_run"):
        return True, "partial_snapshot"
    try:
        finished = datetime.fromisoformat(snapshot["finished"])
    except (KeyError, ValueError):
        return True, "unreadable_snapshot"
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    if now_utc - finished > timedelta(days=MAX_AGE_DAYS):
        return True, "too_old"
    if freshness is not None and not freshness.get("fresh"):
        return True, "data_not_current"
    return False, "fresh"


class AutoRefresher:
    def __init__(self, starter: Callable[[], bool] = engine.start_refresh_background,
                 loader: Callable[[], Optional[dict]] = engine.load_snapshot,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 freshness: Optional[Callable] = None) -> None:
        self._starter, self._loader, self._clock = starter, loader, clock
        self._freshness = freshness or (lambda snap, now: engine.current_freshness(snap, now))
        self._last_attempt: Optional[datetime] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def tick(self) -> str:
        now = self._clock()
        snap = self._loader()
        fresh = self._freshness(snap, now) if snap else None
        need, why = should_refresh(snap, now, fresh)
        if not need:
            return why
        if self._last_attempt and now - self._last_attempt < timedelta(minutes=RETRY_MINUTES):
            return "backoff"
        self._last_attempt = now
        started = self._starter()
        logger.info("Auto-refresh snapshot (%s): %s", why, "dimulai" if started else "sudah berjalan")
        return f"{why}:{'started' if started else 'already_running'}"

    def start(self) -> None:
        if not AUTO_ENABLED or self._thread:
            return

        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception:  # noqa: BLE001
                    logger.exception("Pengecekan auto-refresh gagal")
                self._stop.wait(CHECK_SECONDS)

        self._thread = threading.Thread(target=loop, daemon=True, name="screening-autorefresh")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
