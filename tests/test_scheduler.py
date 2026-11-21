from datetime import datetime, timedelta, timezone

from src.http_auth import check_bearer
from src.screening import scheduler
from src.screening.scheduler import AutoRefresher, should_refresh

WIB = timezone(timedelta(hours=7))


def utc(y, m, d, h, mi=0):
    """Waktu WIB -> UTC (agar kasus uji ditulis dalam jam WIB)."""
    return datetime(y, m, d, h, mi, tzinfo=WIB).astimezone(timezone.utc)


def snap(finished_wib, **extra):
    return {"finished": finished_wib.astimezone(timezone.utc).isoformat(), **extra}


def test_no_or_partial_snapshot_refreshes():
    now = utc(2026, 11, 23, 10)  # Senin
    assert should_refresh(None, now) == (True, "no_snapshot")
    assert should_refresh(snap(utc(2026, 11, 23, 9), partial_run=True), now) == (True, "partial_snapshot")


def test_fresh_before_close_does_not_refresh():
    now = utc(2026, 11, 23, 15)  # Senin sebelum 17:30
    assert should_refresh(snap(utc(2026, 11, 20, 18)), now) == (False, "fresh")


def test_after_close_refreshes_once_then_fresh():
    now = utc(2026, 11, 23, 18)  # Senin 18:00
    assert should_refresh(snap(utc(2026, 11, 20, 18)), now) == (True, "after_close")
    assert should_refresh(snap(utc(2026, 11, 23, 17, 45)), now) == (False, "fresh")


def test_weekend_does_not_refresh_unless_too_old():
    sat = utc(2026, 11, 21, 20)
    assert should_refresh(snap(utc(2026, 11, 20, 18)), sat) == (False, "fresh")
    assert should_refresh(snap(utc(2026, 11, 14, 18)), sat) == (True, "too_old")


def test_tick_backoff_after_attempt():
    clock = {"t": utc(2026, 11, 23, 18)}
    calls = []
    r = AutoRefresher(starter=lambda: calls.append(1) or True, loader=lambda: None, clock=lambda: clock["t"])
    assert r.tick().startswith("no_snapshot:started")
    clock["t"] += timedelta(minutes=10)
    assert r.tick() == "backoff" and len(calls) == 1
    clock["t"] += timedelta(minutes=scheduler.RETRY_MINUTES)
    assert r.tick().startswith("no_snapshot:started") and len(calls) == 2


def test_check_bearer():
    assert check_bearer("Bearer abc", "abc") == (True, 200, "ok")
    assert check_bearer("Bearer salah", "abc")[:2] == (False, 401)
    assert check_bearer("", "abc")[:2] == (False, 401)
    assert check_bearer("Bearer abc", "")[:2] == (False, 503)
