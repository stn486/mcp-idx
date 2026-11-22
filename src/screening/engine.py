"""Engine screening: ambil data batch -> hitung fitur -> simpan snapshot -> saring.

Alur dua tahap supaya cepat dan hemat Yahoo:
  1) refresh_snapshot(): unduh OHLCV universe sekali (puluhan batch), simpan fitur per saham.
  2) screen(): membaca snapshot, menerapkan preset/kriteria. Tidak ada panggilan jaringan,
     jadi mengganti strategi tidak memerlukan unduh ulang.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

from src.screening import rules
from src.screening.features import FEATURE_DOC, compute_features
from src.screening.universe import CONFIG_DIR, DEFAULT_BOARDS, eligible, load_universe

logger = logging.getLogger(__name__)

PRESETS_PATH = Path(os.getenv("SCREENING_PRESETS_FILE", CONFIG_DIR / "presets.json"))
DATA_DIR = Path(os.getenv("SCREENING_DATA_DIR", Path(__file__).resolve().parents[2] / "data" / "screening"))
SNAPSHOT_PATH = DATA_DIR / "snapshot.json"
BATCH_SIZE = int(os.getenv("SCREENING_BATCH_SIZE", "20"))
STALE_DAYS = 4  # bar lebih tua dari ini dibanding bar terbaru snapshot dianggap basi

_state_lock = threading.Lock()
_state: dict[str, Any] = {"running": False}


# ---------------------------------------------------------------- presets
def load_presets() -> dict:
    data = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    known = set(FEATURE_DOC)
    for name, p in data["presets"].items():
        try:
            rules.validate(p["rule"], known)
        except rules.RuleError as e:
            raise rules.RuleError(f"Preset {name}: {e}") from e
    return data


# ---------------------------------------------------------------- snapshot
def load_snapshot() -> Optional[dict]:
    if not SNAPSHOT_PATH.exists():
        return None
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _save_snapshot(snap: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SNAPSHOT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, SNAPSHOT_PATH)


def _frame_for(raw: pd.DataFrame, yahoo_symbol: str, single: bool) -> Optional[pd.DataFrame]:
    try:
        if isinstance(raw.columns, pd.MultiIndex):  # yfinance bisa MultiIndex walau hanya satu ticker
            sub = raw[yahoo_symbol]
        elif single:
            sub = raw
        else:
            return None
    except KeyError:
        return None
    sub = sub.rename(columns=str.lower)
    if not {"open", "high", "low", "close", "volume"} <= set(sub.columns):
        return None
    return sub.dropna(how="all")


def _download(symbols: list[str]) -> pd.DataFrame:
    import yfinance as yf  # impor lambat: tidak dibutuhkan saat screening dari snapshot
    return yf.download(tickers=symbols, period="9mo", interval="1d", group_by="ticker",
                       auto_adjust=False, actions=False, threads=False, progress=False)


def refresh_snapshot(boards: Optional[list[str]] = None, limit: Optional[int] = None,
                     downloader: Callable[[list[str]], pd.DataFrame] = _download,
                     sleep: float = 1.0) -> dict:
    """Unduh data universe dan tulis snapshot. `downloader` bisa diganti untuk tes."""
    universe = load_universe()
    members = eligible(universe, boards)
    if limit:
        members = members[:limit]
    meta = {m["ticker"]: m for m in members}
    rows: dict[str, dict] = {}
    failed: list[dict] = []
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def set_progress(done: int) -> None:
        with _state_lock:
            _state.update(done=done, total=len(members))

    def attempt(batch: list[str]) -> None:
        symbols = [f"{t}.JK" for t in batch]
        raw = None
        for _ in range(2):
            try:
                raw = downloader(symbols)
                if raw is not None and not raw.empty:
                    break
            except Exception as e:  # noqa: BLE001
                logger.warning("Batch gagal (%s): %s", batch[:3], e)
            time.sleep(sleep)
        if raw is None or raw.empty:
            if len(batch) > 1:  # pecah batch agar satu ticker bermasalah tidak menjatuhkan semua
                mid = len(batch) // 2
                attempt(batch[:mid]); attempt(batch[mid:])
            else:
                failed.append({"ticker": batch[0], "reason": "empty_response"})
            return
        for t in batch:
            frame = _frame_for(raw, f"{t}.JK", single=len(symbols) == 1)
            feats = compute_features(frame) if frame is not None else None
            if feats is None:
                failed.append({"ticker": t, "reason": "no_data_or_history_too_short"})
            else:
                feats.update(name=meta[t]["name"], board=meta[t]["board"])
                rows[t] = feats

    tickers = list(meta)
    with _state_lock:
        _state.update(running=True, started=started, done=0, total=len(tickers), error=None)
    try:
        for i in range(0, len(tickers), BATCH_SIZE):
            attempt(tickers[i:i + BATCH_SIZE])
            set_progress(min(i + BATCH_SIZE, len(tickers)))
            time.sleep(sleep)
        if not limit and tickers and len(rows) < MIN_COVERAGE * len(tickers):
            raise RuntimeError(f"Cakupan terlalu rendah ({len(rows)}/{len(tickers)}); snapshot lama dipertahankan.")
        snap = {
            "started": started,
            "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "universe_as_of": universe.get("as_of"),
            "universe_complete": bool(universe.get("complete")),
            "boards": boards or DEFAULT_BOARDS,
            "partial_run": bool(limit),
            "requested": len(tickers),
            "ok": len(rows),
            "failed": failed,
            "rows": rows,
        }
        _save_snapshot(snap)
        return snap
    except Exception as e:  # noqa: BLE001
        with _state_lock:
            _state["error"] = str(e)
        raise
    finally:
        with _state_lock:
            _state["running"] = False


def start_refresh_background(**kwargs: Any) -> bool:
    with _state_lock:
        if _state.get("running"):
            return False
        _state.update(running=True, done=0, total=0, error=None)
    threading.Thread(target=lambda: _safe(kwargs), daemon=True, name="screening-refresh").start()
    return True


def _safe(kwargs: dict) -> None:
    try:
        refresh_snapshot(**kwargs)
    except Exception:  # noqa: BLE001
        logger.exception("Refresh snapshot gagal")


def status() -> dict:
    snap = load_snapshot()
    with _state_lock:
        st = dict(_state)
    out: dict[str, Any] = {"refresh": st, "snapshot": None}
    if snap:
        dates = Counter(r["last_bar_date"] for r in snap["rows"].values())
        out["snapshot"] = {k: snap[k] for k in ("finished", "universe_as_of", "universe_complete",
                                                "boards", "partial_run", "requested", "ok")}
        out["snapshot"]["failed"] = len(snap["failed"])
        out["snapshot"]["latest_bar_date"] = max(dates) if dates else None
    try:
        out["current"] = current_freshness(snap)
    except Exception as e:  # noqa: BLE001
        out["current"] = {"error": str(e)}
    return out


# ---------------------------------------------------------------- screening
# Kebersihan data (bukan strategi): saham "mati" tidak layak jadi kandidat dalam strategi apa pun.
CLEAN_MAX_FLAT_DAYS = int(os.environ.get("SCREENING_CLEAN_MAX_FLAT_DAYS", "10"))   # hari harga datar dalam 20 sesi
CLEAN_MAX_ZERO_VOL_DAYS = int(os.environ.get("SCREENING_CLEAN_MAX_ZERO_VOL_DAYS", "3"))
CLEAN_MIN_AVG_VALUE = float(os.environ.get("SCREENING_CLEAN_MIN_AVG_VALUE", "1e9"))  # estimasi Rp/hari; 0 = nonaktif
# Rata-rata 20 hari bisa terdongkrak lonjakan lama, jadi nilai transaksi hari terakhir juga harus punya batas bawah.
CLEAN_MIN_LAST_VALUE = float(os.environ.get("SCREENING_CLEAN_MIN_LAST_VALUE", "1e8"))  # estimasi Rp/hari; 0 = nonaktif


def _is_dirty(feats: dict, floor: float, last_floor: float = 0.0) -> bool:
    """True bila saham sepi/mati: harga datar, sering tanpa volume, atau nilai transaksi sangat kecil
    (rata-rata 20 sesi di bawah floor, atau nilai hari terakhir di bawah last_floor)."""
    if (feats.get("flat_days20") or 0) >= CLEAN_MAX_FLAT_DAYS:
        return True
    if (feats.get("zero_vol_days20") or 0) >= CLEAN_MAX_ZERO_VOL_DAYS:
        return True
    if floor > 0 and (feats.get("avg_value20_est") or 0) < floor:
        return True
    return last_floor > 0 and (feats.get("value_est") or 0) < last_floor


def _days_between(a: str, b: str) -> int:
    return (datetime.fromisoformat(a) - datetime.fromisoformat(b)).days


def screen(presets: Optional[list[str]] = None, criteria: Optional[dict] = None, match: str = "any",
           filters: Optional[dict] = None, sort_by: str = "value_est", order: str = "desc",
           limit: int = 100, offset: int = 0, include_failed: bool = False, clean: bool = True,
           snapshot: Optional[dict] = None) -> dict:
    snap = snapshot or load_snapshot()
    if not snap:
        return {"error": True, "code": "NO_SNAPSHOT",
                "message": "Snapshot screening belum ada.",
                "suggestion": "Jalankan screening_data dengan action='refresh' atau scripts/refresh_snapshot.py"}
    if match not in ("any", "all"):
        raise rules.RuleError("match harus 'any' atau 'all'")
    if sort_by not in FEATURE_DOC:
        raise rules.RuleError(f"sort_by tidak dikenal: {sort_by}")

    known = set(FEATURE_DOC)
    selected: dict[str, dict] = {}
    if criteria:
        rules.validate(criteria, known)
        selected["CUSTOM"] = criteria
    preset_defs = load_presets()["presets"]
    names = presets if presets is not None else ([] if criteria else list(preset_defs))
    for n in names:
        if n not in preset_defs:
            raise rules.RuleError(f"Preset tidak dikenal: {n}. Tersedia: {sorted(preset_defs)}")
        selected[n] = preset_defs[n]["rule"]
    if not selected:
        raise rules.RuleError("Tidak ada preset atau kriteria yang dipilih")

    needed = set().union(*(rules.used_features(r) for r in selected.values()))
    sample = next(iter(snap["rows"].values()), {})
    missing_features = sorted(needed - set(sample))
    missing_features_for_clean = not {"flat_days20", "zero_vol_days20", "avg_value20_est"} <= set(sample)
    f = filters or {}
    include, exclude = {t.upper() for t in f.get("tickers_include", [])}, {t.upper() for t in f.get("tickers_exclude", [])}
    boards = {b for b in f.get("boards", [])}
    ranges = {k: b for k, b in f.items() if k in FEATURE_DOC}  # mis. {"value_est": [5e9, null]}
    for k, b in ranges.items():
        if not (isinstance(b, list) and len(b) == 2):
            raise rules.RuleError(f"Filter '{k}' harus [min, max] (null = terbuka)")
    floor = 0.0 if "avg_value20_est" in ranges else CLEAN_MIN_AVG_VALUE  # filter eksplisit pemanggil didahulukan
    last_floor = 0.0 if "value_est" in ranges else CLEAN_MIN_LAST_VALUE
    dirty = 0
    reference = max((r["last_bar_date"] for r in snap["rows"].values()), default=None)

    matched, per_setup, stale, excluded_by_filter = [], Counter(), 0, 0
    for ticker, feats in snap["rows"].items():
        if (include and ticker not in include) or ticker in exclude or (boards and feats["board"] not in boards):
            excluded_by_filter += 1
            continue
        if any(feats.get(k) is None or not _within(feats[k], b) for k, b in ranges.items()):
            excluded_by_filter += 1
            continue
        if reference and _days_between(reference, feats["last_bar_date"]) > STALE_DAYS:
            stale += 1
            continue
        hits: dict[str, dict] = {}
        for name, rule in selected.items():
            used: dict = {}
            if rules.evaluate(rule, feats, used):
                hits[name] = used
        if not hits or (match == "all" and len(hits) < len(selected)):
            continue
        if clean and not missing_features_for_clean and _is_dirty(feats, floor, last_floor):
            dirty += 1
            continue
        for n in hits:
            per_setup[n] += 1
        matched.append((ticker, feats, hits))

    has = [m for m in matched if m[1].get(sort_by) is not None]
    has.sort(key=lambda x: x[1][sort_by], reverse=(order == "desc"))
    matched = has + [m for m in matched if m[1].get(sort_by) is None]
    total = len(matched)
    page = matched[offset: offset + limit]

    warnings = []
    if missing_features:
        warnings.append(f"Snapshot lama tidak memuat fitur {missing_features}; kondisi terkait tidak pernah lolos. Jalankan refresh snapshot.")
    if not snap.get("universe_complete"):
        warnings.append("Universe belum terverifikasi lengkap; hasil belum mewakili seluruh BEI.")
    if snap.get("partial_run"):
        warnings.append("Snapshot berasal dari run parsial (limit); bukan seluruh universe.")
    if snap["failed"]:
        warnings.append(f"{len(snap['failed'])} ticker gagal diambil dan TIDAK diperiksa (bukan berarti tanpa setup).")
    if dirty:
        warnings.append(f"{dirty} saham sepi/mati dibuang otomatis (harga datar >= {CLEAN_MAX_FLAT_DAYS} dari 20 sesi, volume nol >= {CLEAN_MAX_ZERO_VOL_DAYS} sesi, nilai transaksi rata-rata 20 sesi < Rp{floor:,.0f}/hari, atau nilai transaksi hari terakhir < Rp{last_floor:,.0f}). Setel clean=false untuk menonaktifkan.")
    if stale:
        warnings.append(f"{stale} ticker dilewati karena bar terakhir basi (>{STALE_DAYS} hari dari {reference}).")
    warnings.append("value_est = close x volume dari Yahoo (estimasi), bukan nilai transaksi resmi BEI.")

    keep = ("close", "change_1d_pct", "value_est", "vol_ratio20", "rsi14", "ema20", "ema50", "atr14",
            "high20_prior", "last_bar_date")
    results = [{
        "ticker": t, "name": ft["name"], "board": ft["board"],
        "setups": list(h), "reasons": h,
        "latest": {k: ft.get(k) for k in keep},
    } for t, ft, h in page]
    shown_to = offset + len(results)
    if shown_to < total:
        warnings.insert(0, f"Baru {shown_to} dari {total} hasil ditampilkan; {total - shown_to} ticker belum terbaca. "
                           f"Ambil sisanya dengan offset={shown_to} (next_offset) sebelum menyimpulkan.")
    out = {
        "snapshot_finished": snap["finished"], "latest_bar_date": reference,
        "universe_as_of": snap.get("universe_as_of"),
        "coverage": {"requested": snap["requested"], "analysed": snap["ok"], "failed": len(snap["failed"]),
                     "stale_skipped": stale, "dropped_as_dead": dirty, "excluded_by_filter": excluded_by_filter},
        "criteria_used": list(selected), "match": match,
        "total_matched": total, "returned": len(results), "offset": offset,
        "next_offset": offset + limit if offset + limit < total else None,
        "per_setup_counts": dict(per_setup),
        "warnings": warnings, "results": results,
    }
    if include_failed:
        out["failed"] = snap["failed"]
    return out


def _within(value: float, bounds: Any) -> bool:
    """bounds: [min, max] dengan None untuk sisi terbuka."""
    lo, hi = bounds
    return (lo is None or value >= lo) and (hi is None or value <= hi)


# ---------------------------------------------------------------- kesegaran data
MIN_COVERAGE = float(os.environ.get("SCREENING_MIN_COVERAGE", "0.7"))
AUTO_RETRY_MINUTES = int(os.environ.get("SCREENING_RETRY_MINUTES", "60"))
_last_auto_refresh: dict = {"at": None}


def current_freshness(snapshot: Optional[dict] = None, now: Optional[datetime] = None) -> dict:
    """Apakah snapshot sudah memuat penutupan bursa terakhir (tanggal acuan dari kalender IHSG)."""
    from . import calendar as cal
    now = now or datetime.now(timezone.utc)
    snap = snapshot if snapshot is not None else load_snapshot()
    expected, source = cal.expected_bar_date(now, cal.trading_dates())
    out = cal.snapshot_freshness(snap or {}, expected)
    out["expected_source"] = source
    return out


def request_refresh(reason: str) -> str:
    """Pemicu dari data: tidak menunggu AI, dibatasi satu kali per AUTO_RETRY_MINUTES."""
    from datetime import timedelta
    with _state_lock:
        if _state.get("running"):
            return "already_running"
    now = datetime.now(timezone.utc)
    last = _last_auto_refresh["at"]
    if last and now - last < timedelta(minutes=AUTO_RETRY_MINUTES):
        return "throttled"
    _last_auto_refresh["at"] = now
    started = start_refresh_background()
    logger.info("Refresh snapshot (%s): %s", reason, "dimulai" if started else "sudah berjalan")
    return "started" if started else "already_running"


def screen_current(**kwargs: Any) -> dict:
    """Seperti screen(), tetapi menolak hasil bila data belum memuat penutupan bursa terakhir."""
    snap = load_snapshot()
    if not snap:
        return screen(**kwargs)  # menghasilkan NO_SNAPSHOT
    fresh = current_freshness(snap)
    if fresh["fresh"]:
        return screen(snapshot=snap, **kwargs)
    action = request_refresh("data_belum_terbarui")
    return {
        "error": True, "code": "DATA_NOT_CURRENT",
        "message": (f"Data belum memuat penutupan {fresh['expected_bar_date']} untuk cukup banyak ticker "
                    f"(baru {fresh['share_current']:.0%}). Refresh diproses otomatis ({action}); coba lagi beberapa menit."),
        "refresh": action, "snapshot_finished": snap.get("finished"), **fresh,
    }
