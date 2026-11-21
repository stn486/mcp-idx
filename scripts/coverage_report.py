"""Analisis cakupan & kebersihan penyaring awal (setup di presets.json atau file lain).

  python scripts/coverage_report.py --min-value 2000000000 --min-close 50
  python scripts/coverage_report.py --horizon 7 --win-pct 7
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.screening import backtest as bt  # noqa: E402
from src.screening import coverage, engine  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--horizon", type=int, default=5)
p.add_argument("--win-pct", type=float, default=5.0)
p.add_argument("--min-value", type=float, default=0.0)
p.add_argument("--min-close", type=float, default=0.0)
p.add_argument("--dead-flat-days", type=int, default=10)
p.add_argument("--max-entry-gap", type=float, default=None)
p.add_argument("--presets-file")
p.add_argument("--out-prefix", default="coverage_report")
a = p.parse_args()

cache = engine.DATA_DIR / "history_cache.csv.gz"
if not cache.exists():
    sys.exit("Cache belum ada. Jalankan: python scripts/export_history_csv.py")
data = bt.load_history(cache)
presets = (json.loads(Path(a.presets_file).read_text(encoding="utf-8"))["presets"]
           if a.presets_file else engine.load_presets()["presets"])
res = coverage.coverage_analysis(data, presets, h=a.horizon, win_pct=a.win_pct, min_avg_value=a.min_value,
                                 min_close=a.min_close, dead_flat_days=a.dead_flat_days,
                                 max_entry_gap_pct=a.max_entry_gap)
md = coverage.to_markdown(res)
(engine.DATA_DIR / f"{a.out_prefix}.md").write_text(md, encoding="utf-8")
(engine.DATA_DIR / f"{a.out_prefix}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
print(md)
