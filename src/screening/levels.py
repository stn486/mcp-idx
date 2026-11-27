"""Level harga mentah untuk satu saham dan kalkulator R/R. Netral: tanpa strategi bawaan.

Modul ini hanya menyediakan ANGKA (swing, high/low, Fibonacci, pivot, gap, jarak dalam ATR).
Memilih level mana yang jadi entry/SL/TP adalah keputusan pemanggil. Kalkulator R/R memakai
fee, slippage, dan aturan lot yang diberikan pemanggil; tidak ada nilai bawaan pribadi.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd

from src.screening.features import clean_ohlcv, feature_frame

WIB = timezone(timedelta(hours=7))
CLOSE_HHMM = (17, 30)          # sebelum jam ini, bar hari ini dianggap belum final
FIB_RETRACE = (0.382, 0.5, 0.618)
FIB_EXT = (1.272, 1.618)
MIN_GAP_ATR = 0.3              # gap lebih kecil dari ini dianggap noise fraksi harga
GAP_LOOKBACK = 60
MIN_BARS = 25
MAX_SEARCH_STEPS = 20000


# ------------------------------------------------------------------ fraksi harga BEI
def tick_size(price: float) -> int:
    """Fraksi harga saham reguler BEI."""
    if price < 200:
        return 1
    if price < 500:
        return 2
    if price < 2000:
        return 5
    if price < 5000:
        return 10
    return 25


def _r2(x: float) -> float:
    return round(float(x), 2)


# ------------------------------------------------------------------ level mentah
def find_swings(d: pd.DataFrame, n: int) -> tuple[list[int], list[int]]:
    """Indeks swing high dan swing low yang SUDAH terkonfirmasi (n bar di kiri dan kanan).

    High: lebih tinggi dari semua n bar kiri dan tidak lebih rendah dari n bar kanan.
    Low: lebih rendah dari semua n bar kiri dan tidak lebih tinggi dari n bar kanan.
    Sisi kanan memakai >= / <= supaya harga kembar (umum di fraksi BEI) tidak menghasilkan swing ganda.
    """
    h, lo = d["high"].to_numpy(), d["low"].to_numpy()
    highs, lows = [], []
    for i in range(n, len(d) - n):
        if h[i] > h[i - n:i].max() and h[i] >= h[i + 1:i + n + 1].max():
            highs.append(i)
        if lo[i] < lo[i - n:i].min() and lo[i] <= lo[i + 1:i + n + 1].min():
            lows.append(i)
    return highs, lows


def _dist(level: float, close: float, atr: float) -> float:
    return round((level - close) / atr, 2)


def _point(d: pd.DataFrame, i: int, price: float, close: float, atr: float) -> dict:
    return {"date": d.index[i].strftime("%Y-%m-%d"), "price": _r2(price), "bars_ago": len(d) - 1 - i,
            "dist_atr": _dist(price, close, atr)}


def _extreme(d: pd.DataFrame, col: str, k: int, close: float, atr: float, offset: int = 0) -> Optional[dict]:
    """High/low tertinggi/terendah k bar terakhir (offset=1: tanpa bar terakhir)."""
    end = len(d) - offset
    if end - k < 0:
        return None
    seg = d[col].iloc[end - k:end]
    i = (seg.idxmax() if col == "high" else seg.idxmin())
    pos = d.index.get_loc(i)
    return _point(d, pos, float(seg.max() if col == "high" else seg.min()), close, atr)


def _fibonacci(d, highs, lows, close, atr) -> Optional[dict]:
    if not highs or not lows:
        return None
    ih, il = highs[-1], lows[-1]
    hi, lo = float(d["high"].iloc[ih]), float(d["low"].iloc[il])
    if hi <= lo:
        return None
    rng = hi - lo
    if il > ih:     # swing low lebih baru: kaki turun (high -> low); retracement = pantulan naik
        leg = "turun"
        ret = [(r, lo + r * rng) for r in FIB_RETRACE]
        ext = [(e, hi - e * rng) for e in FIB_EXT]
    else:           # swing high lebih baru: kaki naik (low -> high); retracement = koreksi turun
        leg = "naik"
        ret = [(r, hi - r * rng) for r in FIB_RETRACE]
        ext = [(e, lo + e * rng) for e in FIB_EXT]
    fmt = lambda pairs: [{"ratio": r, "price": _r2(p), "dist_atr": _dist(p, close, atr)} for r, p in pairs]  # noqa: E731
    return {"leg": leg, "from": _point(d, ih if leg == "turun" else il, hi if leg == "turun" else lo, close, atr),
            "to": _point(d, il if leg == "turun" else ih, lo if leg == "turun" else hi, close, atr),
            "retracement": fmt(ret), "extension": fmt(ext)}


def _pivot_standard(d, close, atr) -> dict:
    h, lo, c = float(d["high"].iloc[-1]), float(d["low"].iloc[-1]), float(d["close"].iloc[-1])
    p = (h + lo + c) / 3
    levels = {"P": p, "R1": 2 * p - lo, "R2": p + (h - lo), "S1": 2 * p - h, "S2": p - (h - lo)}
    return {"basis_date": d.index[-1].strftime("%Y-%m-%d"),
            "levels": {k: {"price": _r2(v), "dist_atr": _dist(v, close, atr)} for k, v in levels.items()}}


def _gaps(d, close, atr) -> list[dict]:
    h, lo = d["high"].to_numpy(), d["low"].to_numpy()
    out = []
    for i in range(max(1, len(d) - GAP_LOOKBACK), len(d)):
        if lo[i] > h[i - 1]:                                   # gap naik
            if (lo[i] - h[i - 1]) / atr < MIN_GAP_ATR:
                continue
            upper = min(lo[i], lo[i + 1:].min()) if i + 1 < len(d) else lo[i]
            if upper > h[i - 1]:
                z_lo, z_hi, kind, size = h[i - 1], upper, "naik", lo[i] - h[i - 1]
            else:
                continue
        elif h[i] < lo[i - 1]:                                 # gap turun
            if (lo[i - 1] - h[i]) / atr < MIN_GAP_ATR:
                continue
            lower = max(h[i], h[i + 1:].max()) if i + 1 < len(d) else h[i]
            if lower < lo[i - 1]:
                z_lo, z_hi, kind, size = lower, lo[i - 1], "turun", lo[i - 1] - h[i]
            else:
                continue
        else:
            continue
        mid = (z_lo + z_hi) / 2
        out.append({"date": d.index[i].strftime("%Y-%m-%d"), "type": kind, "zone_low": _r2(z_lo), "zone_high": _r2(z_hi),
                    "size_atr": round(size / atr, 2), "bars_ago": len(d) - 1 - i, "dist_atr": _dist(mid, close, atr)})
    return list(reversed(out))


def data_status(last_bar_date: str, now_utc: datetime, trading_dates: Optional[set]) -> dict:
    """Apakah bar terakhir sudah memuat penutupan bursa terakhir, dan apakah bar itu belum final."""
    from src.screening.calendar import expected_bar_date
    expected, source = expected_bar_date(now_utc, trading_dates)
    last = date.fromisoformat(last_bar_date)
    now = now_utc.astimezone(WIB)
    partial = last == now.date() and (now.hour, now.minute) < CLOSE_HHMM and now.weekday() < 5
    return {"expected_bar_date": expected.isoformat(), "expected_source": source,
            "current": last >= expected, "last_bar_partial": bool(partial)}


def compute_levels(df: pd.DataFrame, pivot_bars: int = 2, swing_count: int = 5) -> dict[str, Any]:
    """df: OHLCV harian (kolom huruf kecil, index tanggal). Mengembalikan angka mentah, bukan rekomendasi."""
    if not isinstance(pivot_bars, int) or not 1 <= pivot_bars <= 10:
        raise ValueError("pivot_bars harus bilangan bulat 1-10")
    d = clean_ohlcv(df)
    if len(d) < MIN_BARS:
        raise ValueError(f"Data kurang: {len(d)} bar (minimal {MIN_BARS})")
    atr = float(feature_frame(d)["atr14"].iloc[-1])
    if not atr or math.isnan(atr) or atr <= 0:
        raise ValueError("ATR14 tidak tersedia")
    close = float(d["close"].iloc[-1])
    highs, lows = find_swings(d, pivot_bars)
    n = pivot_bars
    tail = d.iloc[-n:]
    pend_hi, pend_lo = tail["high"].idxmax(), tail["low"].idxmin()
    extremes = {
        "low_5d": _extreme(d, "low", 5, close, atr), "low_10d": _extreme(d, "low", 10, close, atr),
        "low_20d": _extreme(d, "low", 20, close, atr),
        "high_20d": _extreme(d, "high", 20, close, atr),
        "high_20d_prior": _extreme(d, "high", 20, close, atr, offset=1),
        "high_60d": _extreme(d, "high", min(60, len(d)), close, atr) if len(d) >= 60 else None,
        "low_60d": _extreme(d, "low", min(60, len(d)), close, atr) if len(d) >= 60 else None,
    }
    return {
        "last_bar_date": d.index[-1].strftime("%Y-%m-%d"), "bars": len(d),
        "close": _r2(close), "atr14": _r2(atr), "atr_pct": round(atr / close * 100, 2), "pivot_bars": n,
        "swing_highs": [_point(d, i, float(d["high"].iloc[i]), close, atr) for i in reversed(highs[-swing_count:])],
        "swing_lows": [_point(d, i, float(d["low"].iloc[i]), close, atr) for i in reversed(lows[-swing_count:])],
        "unconfirmed": {
            "note": f"{n} bar terakhir belum bisa dikonfirmasi sebagai swing; ini ekstrem sementaranya.",
            "high": _point(d, d.index.get_loc(pend_hi), float(tail["high"].max()), close, atr),
            "low": _point(d, d.index.get_loc(pend_lo), float(tail["low"].min()), close, atr)},
        "extremes": extremes,
        "fibonacci": _fibonacci(d, highs, lows, close, atr),
        "pivot_standard": _pivot_standard(d, close, atr),
        "gaps_unfilled": _gaps(d, close, atr),
    }


# ------------------------------------------------------------------ kalkulator R/R
def _evaluate(entry: float, sl: float, tp: float, p: dict) -> dict:
    eff_entry = entry + p["slip_entry"] * tick_size(entry)
    eff_sl = sl - p["slip_sl"] * tick_size(sl)
    if eff_sl <= 0:
        raise ValueError("SL setelah slippage tidak valid (<= 0)")
    fb, fs = p["fee_buy"], p["fee_sell"]
    profit = (tp - eff_entry) - fb * eff_entry - fs * tp
    loss = (eff_entry - eff_sl) + fb * eff_entry + fs * eff_sl
    if loss <= 0:
        raise ValueError("Rugi bersih per saham <= 0; periksa entry dan SL")
    out = {"entry": entry, "rr_net": round(profit / loss, 2),
           "profit_per_share": round(profit, 2), "loss_per_share": round(loss, 2)}
    if p["modal"] is not None:
        budget = p["modal"] * p["risk_pct"] / 100
        lot_risk = math.floor(budget / ((entry - sl) * 100))
        lot_alloc = math.floor(p["modal"] * p["alloc_pct"] / 100 / (entry * 100))
        lot, note = min(lot_risk, lot_alloc), None
        if lot < 1 and p["one_lot_max_alloc_pct"] is not None:
            if entry * 100 <= p["modal"] * p["one_lot_max_alloc_pct"] / 100 and (entry - sl) * 100 <= budget:
                lot, note = 1, "pengecualian 1 lot"
        if lot < 1:
            note = "risiko 1 lot melebihi batas risiko" if (entry - sl) * 100 > budget else "1 lot melebihi batas alokasi"
        lot = max(lot, 0)
        out.update({"lot": lot, "lot_by_risk": lot_risk, "lot_by_alloc": lot_alloc, "lot_note": note,
                    "buy_value": round(entry * lot * 100), "alloc_pct_used": round(entry * lot * 100 / p["modal"] * 100, 1),
                    "profit_net": round(profit * lot * 100), "loss_net": round(loss * lot * 100)})
    return out


def calc_risk_reward(entry: float, sl: float, tp: float, *, entry_high: Optional[float] = None,
                     fee_buy_pct: float = 0.0, fee_sell_pct: float = 0.0,
                     slippage_ticks_entry: int = 0, slippage_ticks_sl: int = 0,
                     modal: Optional[float] = None, risk_pct: Optional[float] = None,
                     alloc_pct: Optional[float] = None, one_lot_max_alloc_pct: Optional[float] = None,
                     min_rr: Optional[float] = None) -> dict[str, Any]:
    """R/R bersih posisi beli. Semua parameter biaya dan batas lot berasal dari pemanggil (tanpa nilai bawaan pribadi).

    profit/saham = (TP - entry) - fee beli x entry - fee jual x TP
    rugi/saham   = (entry - SL) + fee beli x entry + fee jual x SL
    Slippage (dalam tick) berlaku untuk entry market dan SL market; TP dianggap limit.
    Lot = yang lebih kecil dari lot risiko dan lot alokasi (rumus tanpa fee), dibulatkan ke bawah.
    """
    for name, v in (("entry", entry), ("sl", sl), ("tp", tp)):
        if not isinstance(v, (int, float)) or v <= 0:
            raise ValueError(f"{name} harus angka > 0")
    if not sl < entry < tp:
        raise ValueError("Harus berlaku SL < entry < TP (posisi beli)")
    if entry_high is not None and not entry <= entry_high < tp:
        raise ValueError("entry_high harus >= entry dan < TP")
    if modal is not None and (risk_pct is None or alloc_pct is None):
        raise ValueError("Jika modal diisi, risk_pct dan alloc_pct wajib diisi")
    if modal is not None and modal <= 0:
        raise ValueError("modal harus > 0")
    p = {"fee_buy": fee_buy_pct / 100, "fee_sell": fee_sell_pct / 100, "slip_entry": int(slippage_ticks_entry),
         "slip_sl": int(slippage_ticks_sl), "modal": modal, "risk_pct": risk_pct, "alloc_pct": alloc_pct,
         "one_lot_max_alloc_pct": one_lot_max_alloc_pct}
    out: dict[str, Any] = {"at_entry": _evaluate(entry, sl, tp, p), "sl": sl, "tp": tp, "warnings": []}
    if entry_high is not None:
        out["at_entry_high"] = _evaluate(entry_high, sl, tp, p)
    if min_rr is not None:
        best, price, steps = None, sl + tick_size(sl), 0
        while price < tp and steps < MAX_SEARCH_STEPS:
            try:
                if _evaluate(price, sl, tp, p)["rr_net"] >= min_rr:
                    best = price
            except ValueError:
                pass
            price += tick_size(price)
            steps += 1
        out["max_entry_for_min_rr"] = {"min_rr": min_rr, "price": best}
    if fee_buy_pct == 0 and fee_sell_pct == 0:
        out["warnings"].append("Fee 0: R/R bersih sama dengan R/R kotor. Isi fee_buy_pct dan fee_sell_pct bila perlu.")
    return out
