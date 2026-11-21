"""Tes offline: ekuivalensi fitur vektor vs rumus langsung, evaluator vektor, dan backtest."""
import numpy as np
import pandas as pd

from src.screening import backtest as bt
from src.screening import engine, rules
from src.screening.features import clean_ohlcv, compute_features, feature_frame
from src.screening.rules_vec import evaluate_frame


def random_df(n=200, seed=0, drift=0.0):
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(drift, 0.015, n))
    o = c * (1 + rng.normal(0, 0.003, n))
    idx = pd.bdate_range(end="2026-11-20", periods=n)
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.005, "low": np.minimum(o, c) * 0.995,
                         "close": c, "volume": rng.integers(8e5, 3e6, n).astype(float)}, index=idx)


def test_features_match_direct_formulas():
    d = clean_ohlcv(random_df())
    ff = feature_frame(d)
    for i in (80, 120, len(d) - 1):
        w = d.iloc[: i + 1]
        c, h, l, v = w.close, w.high, w.low, w.volume
        ph = h.iloc[-21:-1].max()
        assert abs(ff.high20_prior.iloc[i] - ph) < 1e-9
        assert abs(ff.dist_high20_pct.iloc[i] - (ph - c.iloc[-1]) / ph * 100) < 1e-9
        assert abs(ff.vol_ratio20.iloc[i] - v.iloc[-1] / v.iloc[-21:-1].mean()) < 1e-9
        assert abs(ff.range20_pct.iloc[i] - (h.iloc[-20:].max() / l.iloc[-20:].min() - 1) * 100) < 1e-9
        assert abs(ff.low_ratio_5v5.iloc[i] - l.iloc[-5:].min() / l.iloc[-10:-5].min()) < 1e-9
        assert abs(ff.vol_ratio_5v5.iloc[i] - v.iloc[-5:].mean() / v.iloc[-10:-5].mean()) < 1e-9
        assert abs(ff.ret_60d_pct.iloc[i] - (c.iloc[-1] / c.iloc[-61] - 1) * 100) < 1e-9


def test_compute_features_equals_last_row_and_truncation_invariant():
    df = random_df()
    full = compute_features(df)
    ff = feature_frame(clean_ohlcv(df))
    assert abs(full["rsi14"] - round(ff.rsi14.iloc[-1], 4)) < 1e-9
    # fitur tanggal t tidak boleh bergantung pada data setelah t (anti-lookahead)
    part = compute_features(df.iloc[:150])
    assert abs(part["ema50"] - round(ff.ema50.iloc[149], 4)) < 1e-9
    assert abs(part["atr14"] - round(ff.atr14.iloc[149], 4)) < 1e-9


def test_vector_rules_equal_scalar_rules():
    ff = feature_frame(clean_ohlcv(random_df(seed=3)))
    for name, p in engine.load_presets()["presets"].items():
        vec = evaluate_frame(p["rule"], ff)
        for i in range(70, len(ff), 7):
            row = {k: (None if pd.isna(v) else float(v)) for k, v in ff.iloc[i].items()}
            assert bool(vec.iloc[i]) == rules.evaluate(p["rule"], row), (name, i)


def test_backtest_runs_and_baseline_sane():
    data = {f"T{i:03d}": random_df(seed=i) for i in range(12)}
    res = bt.run_backtest(data, engine.load_presets()["presets"], min_avg_value=0, min_close=0)
    assert res["params"]["tickers_used"] == 12
    assert set(res["baseline"]) == {3, 5, 7}
    for per in res["results"].values():
        for h, r in per.items():
            assert r["n"] >= 0
    assert "Backtest setup" in bt.to_markdown(res)


def test_backtest_entry_exit_and_fee():
    d = random_df(n=120, seed=5)
    ret, mae = bt._forward(clean_ohlcv(d), 3, 0.40)
    dd = clean_ohlcv(d)
    i = 90
    exp = (dd.close.iloc[i + 3] / dd.open.iloc[i + 1] - 1) * 100 - 0.40
    assert abs(ret.iloc[i] - exp) < 1e-9
    lows = min(dd.low.iloc[i + k] for k in (1, 2, 3))
    assert abs(mae.iloc[i] - (lows / dd.open.iloc[i + 1] - 1) * 100) < 1e-9
    assert pd.isna(ret.iloc[-1])  # tanpa data masa depan tidak ada hasil


def test_cooldown():
    assert bt._cooldown(np.array([1, 2, 3, 9, 10, 20]), 5) == [1, 9, 20]
