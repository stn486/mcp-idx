"""Tes: fitur tambahan, filter gap entry, cache portabel, varian setup valid."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.screening import backtest as bt
from src.screening import engine, rules
from src.screening.features import FEATURE_DOC, clean_ohlcv, feature_frame
from tests.test_backtest import random_df


def test_new_features_match_direct_formulas():
    d = clean_ohlcv(random_df(seed=11))
    ff = feature_frame(d)
    for i in (60, 100, len(d) - 1):
        w = d.iloc[: i + 1]
        c, h, l = w.close, w.high, w.low
        assert abs(ff.close_loc.iloc[i] - (c.iloc[-1] - l.iloc[-1]) / (h.iloc[-1] - l.iloc[-1])) < 1e-9
        assert abs(ff.change_5d_pct.iloc[i] - (c.iloc[-1] / c.iloc[-6] - 1) * 100) < 1e-9
        assert abs(ff.ret_20d_pct.iloc[i] - (c.iloc[-1] / c.iloc[-21] - 1) * 100) < 1e-9
        e = c.ewm(span=20, adjust=False).mean()
        assert abs(ff.ema20_slope5_pct.iloc[i] - (e.iloc[-1] / e.iloc[-6] - 1) * 100) < 1e-9


def test_variants_file_valid():
    path = Path(__file__).resolve().parents[1] / "src" / "config" / "presets_variants.json"
    for name, p in json.loads(path.read_text(encoding="utf-8"))["presets"].items():
        rules.validate(p["rule"], set(FEATURE_DOC))


def test_gap_filter_removes_signals():
    data = {f"T{i:03d}": random_df(n=300, seed=i) for i in range(8)}
    presets = engine.load_presets()["presets"]
    base = bt.run_backtest(data, presets)
    strict = bt.run_backtest(data, presets, max_entry_gap_pct=-50)  # tak ada yang lolos
    assert all(r.get(5, {"n": 0})["n"] == 0 for r in strict["results"].values())
    assert any(r[5]["n"] > 0 for r in base["results"].values() if 5 in r)


def test_history_csv_roundtrip_tz_aware(tmp_path):
    df = random_df(n=120, seed=2)
    df.index = df.index.tz_localize("Asia/Jakarta")
    path = tmp_path / "h.csv.gz"
    bt.save_history(path, {"AAAA": df, "BBBB": random_df(n=120, seed=3)})
    back = bt.load_history(path)
    assert set(back) == {"AAAA", "BBBB"}
    assert back["AAAA"].index.tz is None and len(back["AAAA"]) == 120
    assert np.allclose(back["AAAA"].close.to_numpy(), df.close.to_numpy())
