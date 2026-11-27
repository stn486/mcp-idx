"""Level mentah dan kalkulator R/R: angka dicek dengan hitungan tangan."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from src.screening import levels as lv


def frame(highs, lows, closes=None, n_total=None):
    n = len(highs)
    idx = pd.bdate_range(end="2026-11-20", periods=n)
    h, l = np.array(highs, float), np.array(lows, float)
    c = np.array(closes, float) if closes is not None else (h + l) / 2
    return pd.DataFrame({"open": c, "high": h, "low": l, "close": c, "volume": np.full(n, 1e6)}, index=idx)


def zigzag(n=70):
    """Gelombang segitiga: puncak tiap 10 bar (100->120), lembah tiap 10 bar."""
    base = np.array([100 + 2 * abs(((i + 5) % 20) - 10) for i in range(n)], float)
    return frame(base + 1, base - 1)


def test_swings_found_on_triangle_wave():
    d = zigzag()
    highs, lows = lv.find_swings(d, 2)
    assert highs and lows
    for i in highs:
        assert d.high.iloc[i] >= d.high.iloc[i - 2:i + 3].max()
    for i in lows:
        assert d.low.iloc[i] <= d.low.iloc[i - 2:i + 3].min()


def test_equal_highs_do_not_double_count():
    h = [10, 11, 12, 15, 15, 12, 11, 10, 9, 8]
    d = frame(h, [x - 1 for x in h])
    highs, _ = lv.find_swings(d, 2)
    assert highs == [3]


def test_last_n_bars_are_unconfirmed():
    h = list(range(100, 130)) + [140]        # puncak di bar terakhir
    d = frame(h, [x - 1 for x in h])
    highs, _ = lv.find_swings(d, 2)
    assert len(d) - 1 not in highs


def test_compute_levels_structure_and_distances():
    out = lv.compute_levels(zigzag(), pivot_bars=2, swing_count=3)
    assert out["pivot_bars"] == 2 and len(out["swing_highs"]) <= 3
    assert out["swing_highs"][0]["bars_ago"] < out["swing_highs"][-1]["bars_ago"]   # terbaru dulu
    p = out["swing_highs"][0]
    assert abs(p["dist_atr"] - (p["price"] - out["close"]) / out["atr14"]) < 0.02
    assert out["extremes"]["high_60d"] is not None
    assert out["extremes"]["low_5d"]["price"] <= out["close"] + 5
    assert out["extremes"]["high_20d_prior"]["price"] <= out["extremes"]["high_20d"]["price"]


def test_pivot_standard_formula():
    d = frame([110] * 30, [90] * 30, closes=[100] * 30)
    piv = lv.compute_levels(d)["pivot_standard"]["levels"]
    assert piv["P"]["price"] == 100.0
    assert piv["R1"]["price"] == 110.0 and piv["S1"]["price"] == 90.0
    assert piv["R2"]["price"] == 120.0 and piv["S2"]["price"] == 80.0


def test_fibonacci_leg_down_and_up():
    h = [100 + i for i in range(10)] + [110, 109, 108, 107, 106, 105, 104, 103, 102, 101, 100, 99, 98, 99, 100, 101, 102, 103, 104, 105]
    d = frame(h, [x - 2 for x in h])
    fib = lv.compute_levels(d)["fibonacci"]
    assert fib is not None and fib["leg"] in ("naik", "turun")
    ratios = [x["ratio"] for x in fib["retracement"]]
    assert ratios == [0.382, 0.5, 0.618]
    lo, hi = fib["to"]["price"], fib["from"]["price"]
    mid = [x for x in fib["retracement"] if x["ratio"] == 0.5][0]["price"]
    assert mid == round((lo + hi) / 2, 2)


def test_unfilled_gap_up_detected_and_filled_gap_ignored():
    h = [100] * 25 + [110] * 10
    l = [98] * 25 + [108] * 10                  # gap naik 100 -> 108, tidak pernah tertutup
    d = frame(h, l)
    gaps = lv.compute_levels(d)["gaps_unfilled"]
    assert gaps and gaps[0]["type"] == "naik"
    assert gaps[0]["zone_low"] == 100.0 and gaps[0]["zone_high"] == 108.0
    l2 = list(l); l2[-1] = 95                    # low terakhir menembus -> tertutup
    h2 = list(h)
    assert lv.compute_levels(frame(h2, l2))["gaps_unfilled"] == []


def test_validation_errors():
    with pytest.raises(ValueError):
        lv.compute_levels(zigzag(), pivot_bars=0)
    with pytest.raises(ValueError):
        lv.compute_levels(zigzag(10))


def test_tick_size():
    assert [lv.tick_size(p) for p in (150, 300, 1000, 3000, 8000)] == [1, 2, 5, 10, 25]


def test_rr_hand_computed():
    r = lv.calc_risk_reward(1000, 950, 1100, fee_buy_pct=0.15, fee_sell_pct=0.25)["at_entry"]
    assert r["profit_per_share"] == 95.75 and abs(r["loss_per_share"] - 53.875) < 0.01
    assert r["rr_net"] == 1.78


def test_rr_slippage_and_lot():
    out = lv.calc_risk_reward(1000, 950, 1100, fee_buy_pct=0.15, fee_sell_pct=0.25, slippage_ticks_entry=1,
                              modal=3_000_000, risk_pct=1, alloc_pct=20)["at_entry"]
    assert out["lot_by_risk"] == 6 and out["lot_by_alloc"] == 6 and out["lot"] == 6
    assert out["alloc_pct_used"] == 20.0


def test_rr_one_lot_exception():
    # 1 lot = 3.000.000 (100% saham 30.000)... pakai harga 6000: 1 lot = 600.000 (> alokasi 20% dari 2,9jt = 580rb)
    out = lv.calc_risk_reward(6000, 5900, 6300, modal=2_900_000, risk_pct=1, alloc_pct=20,
                              one_lot_max_alloc_pct=25)["at_entry"]
    assert out["lot_by_alloc"] == 0
    # risiko 1 lot = 10.000 <= 29.000 dan nilai 600rb <= 25% x 2,9jt = 725rb -> boleh
    assert out["lot"] == 1 and out["lot_note"] == "pengecualian 1 lot"


def test_rr_one_lot_exceeds_risk():
    out = lv.calc_risk_reward(1000, 500, 1500, modal=1_000_000, risk_pct=1, alloc_pct=50)["at_entry"]
    assert out["lot"] == 0 and "risiko" in out["lot_note"]


def test_rr_max_entry_for_min_rr():
    out = lv.calc_risk_reward(1000, 950, 1100, fee_buy_pct=0.15, fee_sell_pct=0.25, min_rr=1.5)
    m = out["max_entry_for_min_rr"]["price"]
    assert m is not None and m % 5 == 0
    chk = lv.calc_risk_reward(m, 950, 1100, fee_buy_pct=0.15, fee_sell_pct=0.25)["at_entry"]["rr_net"]
    nxt = lv.calc_risk_reward(m + 5, 950, 1100, fee_buy_pct=0.15, fee_sell_pct=0.25)["at_entry"]["rr_net"]
    assert chk >= 1.5 > nxt


def test_rr_input_validation():
    for bad in ((1000, 1000, 1100), (1000, 950, 990), (0, 950, 1100)):
        with pytest.raises(ValueError):
            lv.calc_risk_reward(*bad)
    with pytest.raises(ValueError):
        lv.calc_risk_reward(1000, 950, 1100, modal=1e6)       # risk_pct/alloc_pct wajib


def test_data_status_partial_and_stale():
    dates = {pd.Timestamp("2026-11-26").date(), pd.Timestamp("2026-11-27").date()}
    wib = lambda h, m: datetime(2026, 11, 27, h - 7, m, tzinfo=timezone.utc)   # noqa: E731
    s = lv.data_status("2026-11-27", wib(11, 0), dates)       # tengah sesi, bar hari ini ada tapi belum final
    assert s["last_bar_partial"] is True and s["current"] is True
    s = lv.data_status("2026-11-26", wib(18, 0), dates)       # setelah tutup, bar masih kemarin
    assert s["current"] is False and s["last_bar_partial"] is False
