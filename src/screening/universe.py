"""Universe saham BEI dari ekspor resmi 'Daftar Saham' (xlsx/csv)."""

from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any, Optional

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
UNIVERSE_PATH = Path(os.getenv("SCREENING_UNIVERSE_FILE", CONFIG_DIR / "universe_bei.json"))

BOARD_ALIASES = {
    "utama": "Utama", "main": "Utama",
    "pengembangan": "Pengembangan", "development": "Pengembangan",
    "akselerasi": "Akselerasi", "acceleration": "Akselerasi",
    "pemantauan khusus": "Pemantauan Khusus", "watchlist": "Pemantauan Khusus",
    "ekonomi baru": "Ekonomi Baru", "new economy": "Ekonomi Baru",
}
# Papan yang ikut dipindai. Ubah lewat env SCREENING_BOARDS (mis. "Utama,Pengembangan,Akselerasi").
DEFAULT_BOARDS = [b.strip() for b in os.getenv("SCREENING_BOARDS", "Utama,Pengembangan").split(",") if b.strip()]
TICKER_RE = re.compile(r"^[A-Z0-9]{4}$")

HEADERS = {
    "kode": "ticker", "code": "ticker",
    "nama perusahaan": "name", "company name": "name",
    "tanggal pencatatan": "listing_date", "listing date": "listing_date",
    "saham": "shares", "shares": "shares",
    "papan pencatatan": "board", "listing board": "board",
}


class UniverseError(ValueError):
    pass


def normalize_board(raw: Any) -> str:
    key = str(raw or "").strip().lower()
    if key not in BOARD_ALIASES:
        raise UniverseError(f"Papan tidak dikenal: {raw!r}")
    return BOARD_ALIASES[key]


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        import openpyxl  # hanya dibutuhkan saat membangun universe
        ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
    elif path.suffix.lower() == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
    else:
        raise UniverseError("Format harus .xlsx atau .csv")
    if not rows:
        raise UniverseError("File kosong")
    cols = [HEADERS.get(str(h or "").strip().lower()) for h in rows[0]]
    missing = {"ticker", "name", "board"} - set(cols)
    if missing:
        raise UniverseError(f"Kolom wajib tidak ditemukan: {sorted(missing)}")
    return [{c: v for c, v in zip(cols, r) if c} for r in rows[1:] if any(r)]


def build_from_export(export_path: str, as_of: str, expected_total: Optional[int] = None,
                      out_path: Optional[str] = None) -> dict:
    """Bangun universe_bei.json. Gagal (tanpa menimpa file lama) bila data tidak valid."""
    records, seen = [], set()
    for r in _read_rows(Path(export_path)):
        t = str(r["ticker"]).strip().upper()
        if not TICKER_RE.match(t):
            raise UniverseError(f"Kode tidak valid: {t!r}")
        if t in seen:
            raise UniverseError(f"Kode duplikat: {t}")
        seen.add(t)
        records.append({
            "ticker": t, "name": str(r.get("name") or "").strip(),
            "board": normalize_board(r["board"]),
            "listing_date": str(r.get("listing_date") or ""),
            "shares": str(r.get("shares") or ""),
        })
    if expected_total is not None and len(records) != expected_total:
        raise UniverseError(f"Jumlah kode {len(records)} != total yang diharapkan {expected_total}")
    data = {
        "source": f"Ekspor resmi BEI Daftar Saham ({Path(export_path).name})",
        "as_of": as_of,
        "complete": expected_total is not None,
        "total": len(records),
        "tickers": records,
    }
    target = Path(out_path or UNIVERSE_PATH)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, target)
    return data


def load_universe(path: Optional[str] = None) -> dict:
    p = Path(path or UNIVERSE_PATH)
    if not p.exists():
        raise UniverseError(f"universe_bei.json belum ada ({p}). Jalankan scripts/build_universe.py")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not data.get("tickers"):
        raise UniverseError("Universe kosong")
    return data


def eligible(universe: dict, boards: Optional[list[str]] = None) -> list[dict]:
    wanted = {normalize_board(b) for b in (boards or DEFAULT_BOARDS)}
    return [t for t in universe["tickers"] if t["board"] in wanted]
