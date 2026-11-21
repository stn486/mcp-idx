"""Bangun src/config/universe_bei.json dari ekspor resmi BEI (xlsx/csv).

Contoh:
  python scripts/build_universe.py "D:\\SAHAM\\MCP\\Daftar Saham  - 20261120.xlsx" --as-of 2026-11-20 --expected-total 944
--expected-total = total baris yang tampil di halaman BEI saat unduh. Bila beda, proses berhenti
dan file universe lama tidak ditimpa.
"""
import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.screening.universe import UniverseError, build_from_export, eligible  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("export")
p.add_argument("--as-of", required=True)
p.add_argument("--expected-total", type=int)
a = p.parse_args()
try:
    data = build_from_export(a.export, a.as_of, a.expected_total)
except UniverseError as e:
    sys.exit(f"GAGAL: {e}")
print(f"Universe: {data['total']} kode, complete={data['complete']}")
print("Papan:", dict(collections.Counter(t["board"] for t in data["tickers"])))
print("Eligible default (Utama+Pengembangan):", len(eligible(data)))
