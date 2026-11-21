"""Unduh data universe dan tulis snapshot screening (jalankan terjadwal, mis. setelah bursa tutup).

  python scripts/refresh_snapshot.py            # seluruh universe default
  python scripts/refresh_snapshot.py --limit 40 # uji kecil
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.screening import engine  # noqa: E402

logging.basicConfig(level=logging.INFO)
p = argparse.ArgumentParser()
p.add_argument("--limit", type=int)
p.add_argument("--boards", nargs="*")
a = p.parse_args()
snap = engine.refresh_snapshot(boards=a.boards, limit=a.limit)
print(f"Selesai: diminta {snap['requested']}, berhasil {snap['ok']}, gagal {len(snap['failed'])}")
for f in snap["failed"][:20]:
    print("  gagal:", f["ticker"], f["reason"])
