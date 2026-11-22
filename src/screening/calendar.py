"""Kalender bursa tanpa daftar libur manual.

Bar IHSG (^JKSE) di Yahoo hanya ada pada hari bursa buka, jadi bar IHSG terakhir
yang sudah tersedia menjadi tanggal acuan. Bila IHSG tidak bisa diambil, dipakai
hari kerja terakhir (libur tidak terdeteksi, tetapi refresh tetap dibatasi).
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

WIB = timezone(timedelta(hours=7))
CLOSE_HOUR = int(os.environ.get("SCREENING_REFRESH_AFTER_HOUR_WIB", "17"))
CLOSE_MINUTE = int(os.environ.get("SCREENING_REFRESH_AFTER_MINUTE_WIB", "30"))
CACHE_SECONDS = 1800
MIN_CURRENT_SHARE = 0.5  # minimal separuh ticker harus sudah memuat tanggal acuan

_cache: dict = {"at": 0.0, "dates": None}


def _fetch_ihsg_dates() -> Optional[set]:
    try:
        import yfinance as yf
        raw = yf.download("^JKSE", period="15d", interval="1d", auto_adjust=True, progress=False)
    except Exception as e:  # noqa: BLE001
        logger.warning("Kalender IHSG gagal diambil: %s", e)
        return None
    if raw is None or raw.empty:
        return None
    return {pd.Timestamp(ts).date() for ts in raw.index}


def trading_dates() -> Optional[set]:
    """Tanggal bursa buka menurut IHSG. Di-cache agar tidak membebani Yahoo."""
    now = time.time()
    if now - _cache["at"] > CACHE_SECONDS:
        dates = _fetch_ihsg_dates()
        if dates:
            _cache.update(at=now, dates=dates)
        else:
            _cache["at"] = now - CACHE_SECONDS + 300  # coba lagi 5 menit kemudian
    return _cache["dates"]


def expected_bar_date(now_utc: datetime, dates: Optional[set]) -> tuple:
    """Tanggal penutupan bursa terakhir yang seharusnya sudah ada di data."""
    now = now_utc.astimezone(WIB)
    today = now.date()
    after_close = (now.hour, now.minute) >= (CLOSE_HOUR, CLOSE_MINUTE)
    if dates:
        cands = [d for d in dates if d < today or (d == today and after_close)]
        if cands:
            return max(cands), "ihsg"
    d = today if (after_close and today.weekday() < 5) else today - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d, "weekday_fallback"


def snapshot_freshness(snapshot: dict, expected: date) -> dict:
    rows = list((snapshot or {}).get("rows", {}).values())
    if not rows:
        return {"fresh": False, "share_current": 0.0, "expected_bar_date": expected.isoformat()}
    ok = sum(1 for r in rows if r.get("last_bar_date") and date.fromisoformat(r["last_bar_date"]) >= expected)
    share = ok / len(rows)
    return {"fresh": share >= MIN_CURRENT_SHARE, "share_current": round(share, 3),
            "expected_bar_date": expected.isoformat()}
