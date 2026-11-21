"""Backtest sederhana untuk setup di presets.json.

Asumsi (sengaja konservatif dan transparan):
  - Sinyal terbentuk di close hari t; entry di OPEN hari t+1; exit di CLOSE hari t+h (h = 3/5/7 hari bursa).
  - Fee pulang-pergi (fee_pct) dikurangkan; default 0 = return mentah. Isi sesuai broker Anda. Slippage/gap tidak dimodelkan.
  - Filter likuiditas (min_avg_value, min_close) opsional; default 0 = tanpa filter.
  - Cooldown: sinyal berulang pada ticker yang sama dalam N sesi dihitung satu kali.
  - Pembanding: rata-rata return SEMUA saham likuid pada tanggal yang sama dan horizon yang sama.
Keterbatasan yang tidak bisa dihapus: universe = saham yang tercatat SEKARANG (survivorship bias,
cenderung mengunggulkan hasil); data harian Yahoo; periode pendek hanya mewakili satu rezim pasar.
"""

from __future__ import annotations

import logging
import pickle
import time
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from src.screening.features import MIN_BARS, clean_ohlcv, feature_frame
from src.screening.rules_vec import evaluate_frame

logger = logging.getLogger(__name__)
HORIZONS = (3, 5, 7)


# ------------------------------------------------------------------ data
def _download_adjusted(symbols: list[str], period: str) -> pd.DataFrame:
    import yfinance as yf  # lazy
    return yf.download(tickers=symbols, period=period, interval="1d", group_by="ticker",
                       auto_adjust=True, actions=False, threads=False, progress=False)


def download_history(tickers: list[str], period: str = "2y", batch_size: int = 20, sleep: float = 1.0,
                     downloader: Callable[[list[str], str], pd.DataFrame] = _download_adjusted
                     ) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    """Unduh OHLCV harian (disesuaikan split/dividen) per batch. Mengembalikan (data, gagal)."""
    from src.screening.engine import _frame_for  # hindari impor melingkar saat modul dimuat

    data: dict[str, pd.DataFrame] = {}
    failed: list[dict] = []

    def attempt(batch: list[str]) -> None:
        symbols = [f"{t}.JK" for t in batch]
        raw = None
        for _ in range(2):
            try:
                raw = downloader(symbols, period)
                if raw is not None and not raw.empty:
                    break
            except Exception as e:  # noqa: BLE001
                logger.warning("Batch gagal (%s): %s", batch[:3], e)
            time.sleep(sleep)
        if raw is None or raw.empty:
            if len(batch) > 1:
                mid = len(batch) // 2
                attempt(batch[:mid]); attempt(batch[mid:])
            else:
                failed.append({"ticker": batch[0], "reason": "empty_response"})
            return
        for t in batch:
            frame = _frame_for(raw, f"{t}.JK", single=len(symbols) == 1)
            if frame is None or frame.empty:
                failed.append({"ticker": t, "reason": "no_data"})
            else:
                data[t] = frame

    for i in range(0, len(tickers), batch_size):
        attempt(tickers[i:i + batch_size])
        logger.info("Unduh %d/%d", min(i + batch_size, len(tickers)), len(tickers))
        time.sleep(sleep)
    return data, failed


def _naive_index(df: pd.DataFrame) -> pd.DataFrame:
    idx = pd.to_datetime(df.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    out = df.copy()
    out.index = idx.normalize()
    return out


def save_history(path: Path, data: dict[str, pd.DataFrame]) -> None:
    """Simpan sebagai CSV gzip long-format: portabel lintas versi pandas (pickle tidak)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for t, raw in data.items():
        x = _naive_index(clean_ohlcv(raw))
        x.insert(0, "ticker", t)
        x.index.name = "date"
        frames.append(x.reset_index())
    pd.concat(frames, ignore_index=True).to_csv(path, index=False, compression="gzip")


def load_history(path: Path) -> dict[str, pd.DataFrame]:
    """Baca cache CSV gzip; file .pkl lama tetap bisa dibaca (hanya di versi pandas yang sama)."""
    path = Path(path)
    if path.suffix == ".pkl":
        with open(path, "rb") as fh:
            return {t: _naive_index(clean_ohlcv(df)) for t, df in pickle.load(fh).items()}
    df = pd.read_csv(path, parse_dates=["date"])
    return {t: g.drop(columns="ticker").set_index("date").sort_index() for t, g in df.groupby("ticker")}


# ------------------------------------------------------------------ backtest
def _forward(d: pd.DataFrame, h: int, fee_pct: float) -> tuple[pd.Series, pd.Series]:
    entry = d.open.shift(-1)
    ret = (d.close.shift(-h) / entry - 1) * 100 - fee_pct
    lows = pd.concat([d.low.shift(-k) for k in range(1, h + 1)], axis=1).min(axis=1, skipna=False)
    return ret, (lows / entry - 1) * 100


def _cooldown(positions: np.ndarray, gap: int) -> list[int]:
    kept, last = [], -10**9
    for p in positions:
        if p - last >= gap:
            kept.append(int(p)); last = p
    return kept


def run_backtest(data: dict[str, pd.DataFrame], presets: dict[str, dict], horizons: tuple[int, ...] = HORIZONS,
                 fee_pct: float = 0.0, min_avg_value: float = 0.0, min_close: float = 0.0,
                 cooldown: int = 5, max_entry_gap_pct: Optional[float] = None) -> dict[str, Any]:
    sig_rows: list[pd.DataFrame] = []
    base_rows: list[pd.DataFrame] = []
    used = 0
    for ticker, raw in data.items():
        d = clean_ohlcv(raw)
        if len(d) < MIN_BARS + max(horizons) + 5:
            continue
        used += 1
        ff = feature_frame(d)
        liquid = ((ff.avg_value20_est >= min_avg_value) & (ff.close >= min_close) & (ff.bars >= MIN_BARS)).to_numpy()
        masks = {n: evaluate_frame(p["rule"], ff).to_numpy() & liquid for n, p in presets.items()}
        if max_entry_gap_pct is None:
            gap_ok = np.ones(len(d), dtype=bool)
        else:  # open t+1 terlalu jauh di atas close t (mis. ARA) dianggap tidak bisa dibeli
            gap_ok = ((d.open.shift(-1) / d.close - 1) * 100 <= max_entry_gap_pct).to_numpy()
        for h in horizons:
            ret, mae = _forward(d, h, fee_pct)
            ok = liquid & ret.notna().to_numpy() & mae.notna().to_numpy() & gap_ok
            if ok.any():
                base_rows.append(pd.DataFrame({"h": h, "date": d.index[ok], "ret": ret.to_numpy()[ok]}))
            for name, m in masks.items():
                pos = _cooldown(np.flatnonzero(m), cooldown)
                pos = [p for p in pos if ok[p]]
                if pos:
                    sig_rows.append(pd.DataFrame({
                        "preset": name, "h": h, "ticker": ticker, "date": d.index[pos],
                        "ret": ret.to_numpy()[pos], "mae": mae.to_numpy()[pos]}))

    base = pd.concat(base_rows, ignore_index=True) if base_rows else pd.DataFrame(columns=["h", "date", "ret"])
    sigs = pd.concat(sig_rows, ignore_index=True) if sig_rows else pd.DataFrame(
        columns=["preset", "h", "ticker", "date", "ret", "mae"])

    result: dict[str, Any] = {
        "params": {"fee_roundtrip_pct": fee_pct, "min_avg_value": min_avg_value, "min_close": min_close,
                   "cooldown_sessions": cooldown, "max_entry_gap_pct": max_entry_gap_pct,
                   "entry": "open t+1", "exit": "close t+h",
                   "tickers_used": used},
        "baseline": {}, "results": {n: {} for n in presets},
    }
    for h in horizons:
        b = base[base.h == h]
        if b.empty:
            continue
        by_date = b.groupby("date").ret.mean()
        split = by_date.index[len(by_date) // 2]
        n_days = int(by_date.shape[0])
        result["baseline"][h] = {"n": int(len(b)), "trading_days": n_days, "mean_pct": _r(b.ret.mean()),
                                 "median_pct": _r(b.ret.median()), "win_rate_pct": _r((b.ret > 0).mean() * 100),
                                 "period": [str(by_date.index[0].date()), str(by_date.index[-1].date())]}
        for name in presets:
            s = sigs[(sigs.preset == name) & (sigs.h == h)]
            if s.empty:
                result["results"][name][h] = {"n": 0}
                continue
            ex = s.ret - s.date.map(by_date)
            win, loss = s.ret[s.ret > 0], s.ret[s.ret <= 0]
            first, second = ex[s.date < split], ex[s.date >= split]
            result["results"][name][h] = {
                "n": int(len(s)), "tickers": int(s.ticker.nunique()),
                "signals_per_day": _r(len(s) / n_days),
                "win_rate_pct": _r((s.ret > 0).mean() * 100),
                "mean_pct": _r(s.ret.mean()), "median_pct": _r(s.ret.median()),
                "payoff": _r(win.mean() / abs(loss.mean())) if len(win) and len(loss) and loss.mean() != 0 else None,
                "mean_excess_pct": _r(ex.mean()),
                "excess_first_half": _r(first.mean()) if len(first) else None,
                "excess_second_half": _r(second.mean()) if len(second) else None,
                "mae_median_pct": _r(s.mae.median()),
                "share_mae_le_-5pct": _r((s.mae <= -5).mean() * 100),
            }
    return result


def _r(x: Any, nd: int = 2) -> Optional[float]:
    return None if x is None or pd.isna(x) else round(float(x), nd)


def to_markdown(res: dict[str, Any]) -> str:
    p = res["params"]
    lines = [f"# Backtest setup ({p['tickers_used']} ticker)",
             f"Entry {p['entry']}, exit {p['exit']}, fee pulang-pergi {p['fee_roundtrip_pct']}%, "
             f"nilai transaksi rata-rata >= Rp{p['min_avg_value']:,.0f}/hari, close >= {p['min_close']}, cooldown {p['cooldown_sessions']} sesi, "
             f"gap entry maks {p.get('max_entry_gap_pct')}%.",
             "Ingat: survivorship bias, periode pendek, tanpa slippage. Angka = bukti awal, bukan jaminan.", ""]
    for h, b in res["baseline"].items():
        lines += [f"## Horizon {h} hari  (pembanding semua saham likuid: rata-rata {b['mean_pct']}%, "
                  f"win {b['win_rate_pct']}%, {b['period'][0]} s/d {b['period'][1]})",
                  "| Setup | n | sinyal/hari | win % | rata2 % | median % | payoff | excess % | excess H1 | excess H2 | MAE med % | MAE<=-5% |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for name, per in res["results"].items():
            r = per.get(h, {"n": 0})
            if not r.get("n"):
                lines.append(f"| {name} | 0 | - | - | - | - | - | - | - | - | - | - |")
                continue
            lines.append(f"| {name} | {r['n']} | {r['signals_per_day']} | {r['win_rate_pct']} | {r['mean_pct']} | "
                         f"{r['median_pct']} | {r['payoff']} | {r['mean_excess_pct']} | {r['excess_first_half']} | "
                         f"{r['excess_second_half']} | {r['mae_median_pct']} | {r['share_mae_le_-5pct']}% |")
        lines.append("")
    lines.append("excess = return sinyal dikurangi rata-rata semua saham likuid pada tanggal sama. "
                 "H1/H2 = paruh awal/akhir periode; tanda berbeda berarti hasil tidak stabil.")
    return "\n".join(lines)
