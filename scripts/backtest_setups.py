"""Backtest setup pada data harian universe.

  python scripts/backtest_setups.py --download                       # unduh 2 tahun lalu backtest
  python scripts/backtest_setups.py --min-value 2000000000 --min-close 50
  python scripts/backtest_setups.py --presets-file src/config/presets_variants.json --out-prefix variants
  python scripts/backtest_setups.py --only BREAKOUT PRE_BREAKOUT --max-entry-gap 10

Hasil: data/screening/<out-prefix>.md dan .json (default out-prefix: backtest_report).
Cache data: data/screening/history_cache.csv.gz (portabel). Cache .pkl lama otomatis dikonversi.
"""
import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.screening import backtest as bt  # noqa: E402
from src.screening import engine  # noqa: E402
from src.screening.universe import eligible, load_universe  # noqa: E402

logging.basicConfig(level=logging.WARNING)
p = argparse.ArgumentParser()
p.add_argument("--download", action="store_true")
p.add_argument("--period", default="2y")
p.add_argument("--limit", type=int)
p.add_argument("--fee", type=float, default=0.0, help="fee pulang-pergi (%%), default 0 = mentah")
p.add_argument("--min-value", type=float, default=0.0, help="rata-rata nilai transaksi 20 sesi minimum (Rp), default 0 = tanpa filter")
p.add_argument("--min-close", type=float, default=0.0)
p.add_argument("--cooldown", type=int, default=5)
p.add_argument("--max-entry-gap", type=float, default=None,
               help="lewati sinyal bila open t+1 naik lebih dari N%% dari close t (mis. ARA, tak bisa dibeli)")
p.add_argument("--presets-file", help="JSON berformat sama dengan presets.json")
p.add_argument("--only", nargs="*", help="hanya setup bernama ini")
p.add_argument("--out-prefix", default="backtest_report")
a = p.parse_args()

csv_cache = engine.DATA_DIR / "history_cache.csv.gz"
pkl_cache = engine.DATA_DIR / "history_cache.pkl"
if a.download or not (csv_cache.exists() or pkl_cache.exists()):
    members = [m["ticker"] for m in eligible(load_universe())]
    if a.limit:
        members = members[:a.limit]
    data, failed = bt.download_history(members, period=a.period)
    bt.save_history(csv_cache, data)
    print(f"Unduh: {len(data)} berhasil, {len(failed)} gagal")
elif csv_cache.exists():
    data = bt.load_history(csv_cache)
    print(f"Memakai cache: {len(data)} ticker")
else:
    data = bt.load_history(pkl_cache)
    bt.save_history(csv_cache, data)  # konversi sekali ke format portabel
    print(f"Cache .pkl dikonversi ke {csv_cache.name}: {len(data)} ticker")

if a.presets_file:
    presets = json.loads(Path(a.presets_file).read_text(encoding="utf-8"))["presets"]
else:
    presets = engine.load_presets()["presets"]
if a.only:
    unknown = set(a.only) - set(presets)
    if unknown:
        sys.exit(f"Setup tidak dikenal: {sorted(unknown)}. Tersedia: {sorted(presets)}")
    presets = {k: v for k, v in presets.items() if k in a.only}

res = bt.run_backtest(data, presets, fee_pct=a.fee, min_avg_value=a.min_value, min_close=a.min_close,
                      cooldown=a.cooldown, max_entry_gap_pct=a.max_entry_gap)
md = bt.to_markdown(res)
(engine.DATA_DIR / f"{a.out_prefix}.md").write_text(md, encoding="utf-8")
(engine.DATA_DIR / f"{a.out_prefix}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
print(md)
