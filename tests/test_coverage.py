"""Tes analisis cakupan dan fitur saham mati."""
import numpy as np
import pandas as pd

from src.screening import coverage, engine
from src.screening.features import clean_ohlcv, feature_frame
from tests.test_backtest import random_df


def test_dead_features():
    n = 120
    idx = pd.bdate_range(end="2026-11-20", periods=n)
    c = np.full(n, 100.0)
    c[-5:] = [101, 102, 103, 104, 105]            # 5 sesi terakhir bergerak, 15 sebelumnya datar
    v = np.full(n, 1e6); v[-3:] = 0
    d = pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": v}, index=idx)
    ff = feature_frame(clean_ohlcv(d))
    assert ff.flat_days20.iloc[-1] == 15
    assert ff.zero_vol_days20.iloc[-1] == 3


def test_coverage_runs_and_is_consistent():
    data = {f"T{i:03d}": random_df(n=300, seed=i) for i in range(15)}
    res = coverage.coverage_analysis(data, engine.load_presets()["presets"])
    rows = res["rows"]
    assert rows["UNION"]["n"] >= max(r.get("n", 0) for k, r in rows.items() if k not in ("UNION", "UNION_NOT_DEAD"))
    assert 0 <= rows["UNION"]["recall_pct"] <= 100
    assert rows["UNION_NOT_DEAD"]["n"] <= rows["UNION"]["n"]
    assert "Cakupan" in coverage.to_markdown(res)


def test_random_walk_lift_near_one():
    data = {f"T{i:03d}": random_df(n=400, seed=100 + i) for i in range(40)}
    res = coverage.coverage_analysis(data, engine.load_presets()["presets"])
    assert 0.6 < res["rows"]["UNION"]["lift"] < 1.5  # data acak: tidak ada keunggulan nyata
