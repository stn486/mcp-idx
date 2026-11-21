"""Tes offline engine screening (tanpa jaringan, tanpa yfinance/mcp)."""
import numpy as np
import pandas as pd
import pytest

from src.screening import engine, rules
from src.screening.features import FEATURE_DOC, compute_features


def make_df(closes, vols=None, spread=0.01):
    n = len(closes)
    idx = pd.bdate_range(end="2026-11-20", periods=n)
    c = np.array(closes, float)
    return pd.DataFrame({"open": c, "high": c * (1 + spread), "low": c * (1 - spread), "close": c,
                         "volume": vols if vols is not None else np.full(n, 1_000_000.0)}, index=idx)


def test_too_short_returns_none():
    assert compute_features(make_df([100] * 40)) is None


def test_breakout_detected():
    closes = [100 + 0.05 * i for i in range(79)] + [112]
    vols = [1_000_000] * 79 + [2_000_000]
    f = compute_features(make_df(closes, vols))
    assert f["dist_high20_pct"] < 0 and f["vol_ratio20"] >= 1.5
    preset = engine.load_presets()["presets"]["BREAKOUT"]["rule"]
    assert rules.evaluate(preset, f)


def test_flat_not_breakout_but_base():
    f = compute_features(make_df([100] * 80))
    presets = engine.load_presets()["presets"]
    assert not rules.evaluate(presets["BREAKOUT"]["rule"], f)
    assert f["range20_pct"] <= 10


def test_none_feature_never_passes():
    assert not rules.evaluate({"feature": "rsi14", "op": ">", "value": 0}, {"rsi14": None})


def test_validate_rejects_unknown():
    with pytest.raises(rules.RuleError):
        rules.validate({"all": [{"feature": "nope", "op": ">", "value": 1}]}, set(FEATURE_DOC))
    with pytest.raises(rules.RuleError):
        rules.validate({"feature": "rsi14", "op": "~", "value": 1}, set(FEATURE_DOC))


def test_all_presets_valid():
    names = set(engine.load_presets()["presets"])
    assert {"EARLY_REVERSAL", "HEALTHY_PULLBACK", "BASE_CONSOLIDATION", "PRE_BREAKOUT", "BREAKOUT",
            "TREND_CONTINUATION", "MOMENTUM"} <= names


def _snap():
    rows = {}
    for t, closes, vols in [
        ("AAAA", [100 + 0.05 * i for i in range(79)] + [112], [1e6] * 79 + [2e6]),
        ("BBBB", [100] * 80, None),
    ]:
        f = compute_features(make_df(closes, vols))
        f.update(name=t, board="Utama")
        rows[t] = f
    return {"finished": "x", "requested": 3, "ok": 2, "failed": [{"ticker": "CCCC", "reason": "empty_response"}],
            "rows": rows, "universe_complete": True}


def test_screen_pagination_and_warnings():
    out = engine.screen(presets=["BREAKOUT"], snapshot=_snap(), limit=1, clean=False)
    assert out["total_matched"] == 1 and out["results"][0]["ticker"] == "AAAA"
    assert any("gagal" in w for w in out["warnings"])
    assert out["coverage"]["failed"] == 1


def test_custom_criteria_and_filter():
    crit = {"all": [{"feature": "range20_pct", "op": "<=", "value": 10}]}
    out = engine.screen(criteria=crit, snapshot=_snap(), clean=False)
    assert {r["ticker"] for r in out["results"]} == {"BBBB"}
    out = engine.screen(criteria=crit, snapshot=_snap(), filters={"close": [200, None]}, clean=False)
    assert out["total_matched"] == 0


def test_stale_rows_skipped():
    snap = _snap()
    snap["rows"]["BBBB"]["last_bar_date"] = "2026-10-01"
    out = engine.screen(presets=["BASE_CONSOLIDATION"], snapshot=snap)
    assert out["coverage"]["stale_skipped"] == 1


def test_old_snapshot_missing_feature_warns():
    snap = _snap()
    for r in snap["rows"].values():
        r.pop("ema20_slope5_pct", None)
    out = engine.screen(presets=["MOMENTUM"], snapshot=snap)
    assert any("Snapshot lama" in w for w in out["warnings"])


def test_clean_drops_dead_stocks_but_clean_false_keeps_them():
    crit = {"all": [{"feature": "range20_pct", "op": "<=", "value": 10}]}
    snap = _snap()  # BBBB: harga datar 20 sesi & nilai transaksi kecil => dianggap mati
    out = engine.screen(criteria=crit, snapshot=snap)
    assert out["total_matched"] == 0 and out["coverage"]["dropped_as_dead"] == 1
    assert any("sepi/mati" in w for w in out["warnings"])
    out = engine.screen(criteria=crit, snapshot=snap, clean=False)
    assert {r["ticker"] for r in out["results"]} == {"BBBB"}
