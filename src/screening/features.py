"""Hitung fitur skalar per saham dari OHLCV harian.

Semua aturan screening hanya merujuk nama fitur di bawah ini. Menambah fitur
baru di sini otomatis bisa dipakai di presets.json atau kriteria kustom.

feature_frame() menghitung fitur untuk SETIAP tanggal (dipakai backtest);
compute_features() mengambil baris terakhirnya (dipakai screening harian),
sehingga backtest dan screening memakai definisi yang persis sama.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

MIN_BARS = 61  # cukup untuk return 60 sesi dan jendela 20 sesi sebelumnya

FEATURE_DOC = {
    "close": "Harga penutupan terakhir",
    "change_1d_pct": "Perubahan close vs sesi sebelumnya (%)",
    "volume": "Volume sesi terakhir",
    "value_est": "Estimasi nilai transaksi = close x volume (BUKAN data resmi BEI)",
    "avg_value20_est": "Rata-rata estimasi nilai transaksi 20 sesi sebelumnya",
    "ema20": "EMA 20", "ema50": "EMA 50",
    "close_over_ema20": "close / EMA20", "close_over_ema50": "close / EMA50",
    "ema20_over_ema50": "EMA20 / EMA50",
    "rsi14": "RSI 14 (Wilder)", "atr14": "ATR 14 (Wilder)", "atr_pct": "ATR14 / close (%)",
    "min_dist_ema_atr": "Jarak terdekat close ke EMA20/EMA50 dalam satuan ATR",
    "vol_ratio20": "Volume terakhir / rata-rata volume 20 sesi sebelumnya",
    "vol_ratio_5v5": "Rata-rata volume 5 sesi terakhir / 5 sesi sebelumnya",
    "high20_prior": "High tertinggi 20 sesi sebelumnya (tanpa bar terakhir)",
    "dist_high20_pct": "Jarak close di bawah high20_prior (%); negatif = sudah di atasnya",
    "range20_pct": "Rentang high/low 20 sesi terakhir (%)",
    "atr_ratio_5v10": "ATR rata-rata 5 sesi terakhir / 10 sesi sebelumnya (<1 = menyempit)",
    "ret_60d_pct": "Return 60 sesi (%)",
    "low_ratio_5v5": "Low terendah 5 sesi terakhir / 5 sesi sebelumnya (>1 = higher low)",
    "close_loc": "Posisi close dalam rentang low-high bar terakhir (0 = di low, 1 = di high)",
    "change_5d_pct": "Perubahan close vs 5 sesi lalu (%)",
    "ret_20d_pct": "Return 20 sesi (%)",
    "ema20_slope5_pct": "Kemiringan EMA20: perubahan EMA20 dalam 5 sesi (%)",
    "flat_days20": "Jumlah sesi dalam 20 sesi terakhir dengan close sama persis seperti sesi sebelumnya (tinggi = saham 'mati')",
    "zero_vol_days20": "Jumlah sesi bervolume nol dalam 20 sesi terakhir",
    "bars": "Jumlah bar harian tersedia",
}


def clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Kolom open/high/low/close/volume (huruf kecil); buang baris janggal, urutkan, hapus duplikat."""
    d = df[["open", "high", "low", "close", "volume"]].astype(float)
    d = d.replace([float("inf"), float("-inf")], pd.NA).dropna().sort_index()
    d = d[~d.index.duplicated(keep="last")]
    return d[(d.close > 0) & (d.high >= d.low)]


def _r(a: pd.Series, b: pd.Series) -> pd.Series:
    """Rasio a/b; NaN bila penyebut <= 0."""
    return a / b.where(b > 0)


def feature_frame(d: pd.DataFrame) -> pd.DataFrame:
    """Fitur per tanggal dari OHLCV yang sudah dibersihkan. Baris awal berisi NaN (data kurang)."""
    c, h, l, v = d.close, d.high, d.low, d.volume
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, float("nan")))
    rsi = rsi.where(loss != 0, 100.0).where(~((gain == 0) & (loss == 0)), 50.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    atr_ok = atr.where(atr > 0)

    prior_high20 = h.shift(1).rolling(20).max()          # 20 bar sebelum bar ini
    avg_vol20 = v.shift(1).rolling(20).mean()
    base_low, base_high = l.rolling(20).min(), h.rolling(20).max()

    f = pd.DataFrame(index=d.index)
    f["close"] = c
    f["change_1d_pct"] = (c / c.shift(1) - 1) * 100
    f["volume"] = v
    f["value_est"] = c * v
    f["avg_value20_est"] = (c * v).shift(1).rolling(20).mean()
    f["ema20"], f["ema50"] = ema20, ema50
    f["close_over_ema20"], f["close_over_ema50"] = c / ema20, c / ema50
    f["ema20_over_ema50"] = ema20 / ema50
    f["rsi14"] = rsi
    f["atr14"] = atr
    f["atr_pct"] = atr / c * 100
    f["min_dist_ema_atr"] = pd.concat([(c - ema20).abs(), (c - ema50).abs()], axis=1).min(axis=1) / atr_ok
    f["vol_ratio20"] = _r(v, avg_vol20)
    f["vol_ratio_5v5"] = _r(v.rolling(5).mean(), v.shift(5).rolling(5).mean())
    f["high20_prior"] = prior_high20
    f["dist_high20_pct"] = (prior_high20 - c) / prior_high20.where(prior_high20 > 0) * 100
    f["range20_pct"] = (base_high / base_low.where(base_low > 0) - 1) * 100
    f["atr_ratio_5v10"] = _r(atr.rolling(5).mean(), atr.shift(5).rolling(10).mean())
    f["ret_60d_pct"] = (c / c.shift(60) - 1) * 100
    f["low_ratio_5v5"] = _r(l.rolling(5).min(), l.shift(5).rolling(5).min())
    f["close_loc"] = (c - l) / (h - l).where(h > l)
    f["change_5d_pct"] = (c / c.shift(5) - 1) * 100
    f["ret_20d_pct"] = (c / c.shift(20) - 1) * 100
    f["ema20_slope5_pct"] = (ema20 / ema20.shift(5) - 1) * 100
    f["flat_days20"] = (c.diff() == 0).astype(float).rolling(20).sum()
    f["zero_vol_days20"] = (v == 0).astype(float).rolling(20).sum()
    f["bars"] = range(1, len(d) + 1)
    return f.replace([float("inf"), float("-inf")], float("nan"))


def _num(x: Any, nd: int = 4) -> Optional[float]:
    try:
        if x is None or pd.isna(x):
            return None
        return round(float(x), nd)
    except (TypeError, ValueError):
        return None


def compute_features(df: pd.DataFrame) -> Optional[dict[str, Any]]:
    """df: kolom open/high/low/close/volume dengan index tanggal. None bila data kurang/janggal."""
    if df is None or df.empty:
        return None
    d = clean_ohlcv(df)
    if len(d) < MIN_BARS:
        return None
    last = feature_frame(d).iloc[-1]
    if pd.isna(last["atr14"]) or last["atr14"] <= 0:
        return None
    out = {k: _num(last[k], 4) for k in FEATURE_DOC}
    out["bars"] = len(d)
    out["last_bar_date"] = d.index[-1].strftime("%Y-%m-%d")
    return out
