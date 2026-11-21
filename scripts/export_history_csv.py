"""Ubah cache unduhan lama (.pkl) menjadi CSV gzip portabel. Cepat, tanpa internet.

  python scripts/export_history_csv.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.screening import backtest as bt  # noqa: E402
from src.screening import engine  # noqa: E402

pkl = engine.DATA_DIR / "history_cache.pkl"
out = engine.DATA_DIR / "history_cache.csv.gz"
if not pkl.exists():
    sys.exit(f"Tidak ada {pkl}. Jalankan: python scripts/backtest_setups.py --download")
data = bt.load_history(pkl)
bt.save_history(out, data)
print(f"Selesai: {len(data)} ticker -> {out} ({out.stat().st_size/1e6:.1f} MB)")
