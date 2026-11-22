from datetime import datetime, timedelta, timezone

from src.http_auth import check_bearer
from src.screening import scheduler
from src.screening.scheduler import AutoRefresher, should_refresh

WIB = timezone(timedelta(hours=7))
CUR = {"fresh": True}
STALE = {"fresh": False}


def utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=WIB).astimezone(timezone.utc)


def snap(finished_utc, **extra):
    return {"finished": finished_utc.isoformat(), **extra}


def test_no_or_partial_snapshot_refreshes():
    now = utc(2026, 11, 23, 10)
    assert should_refresh(None, now) == (True, "no_snapshot")
    assert should_refresh(snap(utc(2026, 11, 23, 9), partial_run=True), now) == (True, "partial_snapshot")


def test_current_data_does_not_refresh():
    now = utc(2026, 11, 23, 18)
    assert should_refresh(snap(utc(2026, 11, 23, 18)), now, CUR) == (False, "fresh")


def test_data_not_current_triggers_refresh():
    now = utc(2026, 11, 23, 18)
    assert should_refresh(snap(utc(2026, 11, 20, 18)), now, STALE) == (True, "data_not_current")


def test_too_old_triggers_refresh():
    now = utc(2026, 11, 23, 10)
    assert should_refresh(snap(utc(2026, 11, 14, 18)), now, CUR) == (True, "too_old")


def test_tick_backoff_after_attempt():
    clock = {"t": utc(2026, 11, 23, 18)}
    calls = []
    r = AutoRefresher(starter=lambda: calls.append(1) or True,
                      loader=lambda: snap(utc(2026, 11, 23, 17)),
                      clock=lambda: clock["t"],
                      freshness=lambda s, n: STALE)
    assert r.tick() == "data_not_current:started" and len(calls) == 1
    clock["t"] += timedelta(minutes=10)
    assert r.tick() == "backoff" and len(calls) == 1
    clock["t"] += timedelta(minutes=scheduler.RETRY_MINUTES)
    assert r.tick() == "data_not_current:started" and len(calls) == 2


def test_check_bearer():
    assert check_bearer("Bearer abc", "abc") == (True, 200, "ok")
    assert check_bearer("Bearer salah", "abc")[:2] == (False, 401)
    assert check_bearer("", "abc")[:2] == (False, 401)
    assert check_bearer("Bearer abc", "")[:2] == (False, 503)
