"""Analisis cakupan & kebersihan penyaring awal.

Pertanyaan yang dijawab (bukan 'setup mana yang untung'):
  - Cakupan: dari semua saham-hari yang kemudian naik besar ("winner"), berapa persen ikut lolos?
  - Kebersihan: berapa persen hasil adalah saham 'mati' (harga sering tidak berubah)?
  - Beban: berapa kandidat per hari yang harus dianalisis pemanggil?
Unit = saham-hari (tanpa cooldown). Winner = return h hari (entry open t+1, exit close t+h) >= win_pct.
"Clean winner" = winner yang tidak sempat turun lebih dari win_pct di tengah jalan.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from src.screening.backtest import _forward
from src.screening.features import MIN_BARS, clean_ohlcv, feature_frame
from src.screening.rules_vec import evaluate_frame


def coverage_analysis(data: dict[str, pd.DataFrame], presets: dict[str, dict], h: int = 5, win_pct: float = 5.0,
                      min_avg_value: float = 0.0, min_close: float = 0.0, dead_flat_days: int = 10,
                      max_entry_gap_pct: Optional[float] = None) -> dict[str, Any]:
    parts: list[pd.DataFrame] = []
    for ticker, raw in data.items():
        d = clean_ohlcv(raw)
        if len(d) < MIN_BARS + h + 5:
            continue
        ff = feature_frame(d)
        liquid = ((ff.avg_value20_est >= min_avg_value) & (ff.close >= min_close) & (ff.bars >= MIN_BARS)).to_numpy()
        ret, mae = _forward(d, h, 0.0)
        ok = liquid & ret.notna().to_numpy() & mae.notna().to_numpy()
        if max_entry_gap_pct is not None:
            ok &= ((d.open.shift(-1) / d.close - 1) * 100 <= max_entry_gap_pct).to_numpy()
        if not ok.any():
            continue
        win = (ret >= win_pct).to_numpy()
        part = pd.DataFrame({
            "ticker": ticker, "date": d.index,
            "win": win, "clean": win & (mae > -win_pct).to_numpy(),
            "dead": (ff.flat_days20 >= dead_flat_days).to_numpy(),
        })
        for name, p in presets.items():
            part[name] = evaluate_frame(p["rule"], ff).to_numpy()
        parts.append(part[ok])
    if not parts:
        return {"error": "tidak ada data"}
    big = pd.concat(parts, ignore_index=True)
    names = list(presets)
    big["UNION"] = big[names].any(axis=1)
    days = big.date.nunique()
    base_win, base_clean = big.win.mean(), big.clean.mean()

    def row(mask: pd.Series) -> dict[str, Any]:
        n = int(mask.sum())
        if n == 0:
            return {"n": 0}
        prec, cprec = big.win[mask].mean(), big.clean[mask].mean()
        return {
            "per_day": round(n / days, 1), "share_of_universe_pct": round(n / len(big) * 100, 1),
            "precision_pct": round(prec * 100, 2), "lift": round(prec / base_win, 2) if base_win else None,
            "recall_pct": round(big.win[mask].sum() / big.win.sum() * 100, 1),
            "clean_precision_pct": round(cprec * 100, 2),
            "clean_recall_pct": round(big.clean[mask].sum() / big.clean.sum() * 100, 1),
            "dead_share_pct": round(big.dead[mask].mean() * 100, 1),
            "n": n,
        }

    return {
        "params": {"horizon": h, "win_pct": win_pct, "min_avg_value": min_avg_value, "min_close": min_close,
                   "dead_flat_days": dead_flat_days, "max_entry_gap_pct": max_entry_gap_pct, "days": int(days)},
        "universe": {"stock_days": int(len(big)), "per_day": round(len(big) / days, 1),
                     "base_winner_pct": round(base_win * 100, 2), "base_clean_winner_pct": round(base_clean * 100, 2),
                     "dead_share_pct": round(big.dead.mean() * 100, 1),
                     "winner_rate_dead_pct": round(big.win[big.dead].mean() * 100, 2) if big.dead.any() else None,
                     "winner_rate_active_pct": round(big.win[~big.dead].mean() * 100, 2)},
        "rows": {**{n: row(big[n]) for n in names}, "UNION": row(big["UNION"]),
                 "UNION_NOT_DEAD": row(big["UNION"] & ~big.dead)},
    }


def to_markdown(res: dict[str, Any]) -> str:
    p, u = res["params"], res["universe"]
    L = [f"# Cakupan & kebersihan penyaring awal ({p['days']} hari bursa)",
         f"Winner = return {p['horizon']} hari >= {p['win_pct']}% (entry open t+1). Clean = winner tanpa turun > {p['win_pct']}% di tengah jalan.",
         f"Saham 'mati' = >= {p['dead_flat_days']} dari 20 sesi terakhir close tidak berubah. Likuiditas >= Rp{p['min_avg_value']:,.0f}, close >= {p['min_close']}.",
         "",
         f"Semesta: {u['per_day']} saham/hari. Winner: {u['base_winner_pct']}%, clean winner: {u['base_clean_winner_pct']}%. "
         f"Saham mati: {u['dead_share_pct']}% dari semesta; peluang winner saham mati {u['winner_rate_dead_pct']}% vs aktif {u['winner_rate_active_pct']}%.",
         "",
         "| Penyaring | per hari | % semesta | winner % | lift | recall % | clean recall % | mati % |",
         "|---|---|---|---|---|---|---|---|"]
    for name, r in res["rows"].items():
        if not r.get("n"):
            L.append(f"| {name} | 0 | - | - | - | - | - | - |")
        else:
            L.append(f"| {name} | {r['per_day']} | {r['share_of_universe_pct']} | {r['precision_pct']} | {r['lift']} | "
                     f"{r['recall_pct']} | {r['clean_recall_pct']} | {r['dead_share_pct']} |")
    L += ["", "lift = winner% penyaring / winner% semesta (1,0 = tidak lebih baik dari acak). "
          "recall = porsi seluruh winner yang ikut lolos. Penyaring awal yang baik: recall tinggi, mati% rendah, per hari terkelola."]
    return "\n".join(L)
