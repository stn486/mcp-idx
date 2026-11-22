from datetime import date, datetime, timedelta, timezone

from src.screening import calendar as cal

WIB = timezone(timedelta(hours=7))


def utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=WIB).astimezone(timezone.utc)


def test_expected_is_last_ihsg_day_before_today():
    dates = {date(2026, 11, 19), date(2026, 11, 20)}
    assert cal.expected_bar_date(utc(2026, 11, 22, 9), dates) == (date(2026, 11, 20), "ihsg")


def test_today_counts_only_after_close():
    dates = {date(2026, 11, 20), date(2026, 11, 23)}
    assert cal.expected_bar_date(utc(2026, 11, 23, 16), dates)[0] == date(2026, 11, 20)
    assert cal.expected_bar_date(utc(2026, 11, 23, 18), dates)[0] == date(2026, 11, 23)


def test_holiday_is_skipped_without_manual_list():
    dates = {date(2026, 11, 18)}  # 19 November tidak ada bar IHSG -> bursa tutup
    assert cal.expected_bar_date(utc(2026, 11, 19, 18), dates)[0] == date(2026, 11, 18)


def test_weekday_fallback_without_ihsg():
    assert cal.expected_bar_date(utc(2026, 11, 22, 9), None) == (date(2026, 11, 20), "weekday_fallback")
    assert cal.expected_bar_date(utc(2026, 11, 23, 18), None) == (date(2026, 11, 23), "weekday_fallback")


def test_freshness_share():
    snap = {"rows": {"A": {"last_bar_date": "2026-11-23"},
                     "B": {"last_bar_date": "2026-11-20"},
                     "C": {"last_bar_date": "2026-11-23"}}}
    f = cal.snapshot_freshness(snap, date(2026, 11, 23))
    assert f["fresh"] and f["share_current"] == 0.667
    assert cal.snapshot_freshness({"rows": {}}, date(2026, 11, 23))["fresh"] is False
