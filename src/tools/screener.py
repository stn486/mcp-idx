"""Tool MCP: screen_stocks dan screening_data."""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.types import Tool

from src.screening import engine
from src.screening.features import FEATURE_DOC
from src.screening.rules import RuleError
from src.screening.universe import UniverseError


def get_screen_stocks_tool() -> Tool:
    return Tool(
        name="screen_stocks",
        description=(
            "Jika data belum memuat penutupan bursa terakhir, tool menjawab DATA_NOT_CURRENT dan refresh berjalan otomatis; coba lagi beberapa menit. Penyaring awal: daripada menyisir ~900 ticker satu per satu, panggil tool ini (tanpa argumen pun bisa) dan terima daftar ticker yang sudah bersih (saham sepi/mati dibuang otomatis) dan lolos salah satu kategori setup. Hasil bisa banyak, kategori sengaja tidak dipersempit; analisis akhir tetap oleh pemanggil sesuai aturannya sendiri. Argumen bersifat OPSIONAL: presets (pilih kategori tertentu), criteria (aturan sendiri), filters (mis. likuiditas), sort_by (urutan baca). Hasil memuat alasan lolos, cakupan, dan peringatan. Tool lain tetap bisa dipakai untuk ticker mana pun."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "presets": {"type": "array", "items": {"type": "string"},
                            "description": "Nama setup. Default: semua preset standar (lihat screening_data action=presets)."},
                "criteria": {"type": "object",
                             "description": "Kriteria kustom: {\"all\":[{\"feature\":\"rsi14\",\"op\":\"between\",\"value\":[40,55]}]}. "
                                            "Operator: > >= < <= == != between; value boleh nama fitur."},
                "match": {"type": "string", "enum": ["any", "all"], "default": "any",
                          "description": "any = lolos salah satu setup; all = lolos semua yang dipilih"},
                "filters": {"type": "object",
                            "description": "boards: [..]; tickers_include/tickers_exclude: [..]; rentang fitur apa pun [min,max], "
                                           "mis. {\"value_est\":[5e9,null],\"close\":[50,null]}"},
                "clean": {"type": "boolean", "default": True, "description": "Buang saham sepi/mati (harga datar, volume nol, nilai transaksi sangat kecil). false = tampilkan semua yang lolos setup"},
                "sort_by": {"type": "string", "default": "value_est", "description": "Nama fitur untuk urutan"},
                "order": {"type": "string", "enum": ["asc", "desc"], "default": "desc"},
                "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500,
                          "description": "Ukuran halaman (bukan batas hasil); lanjutkan dengan offset=next_offset"},
                "offset": {"type": "integer", "default": 0, "minimum": 0},
                "include_failed": {"type": "boolean", "default": False},
            },
        },
    )


def get_screening_data_tool() -> Tool:
    return Tool(
        name="screening_data",
        description=(
            "Kelola data screening. action=status (umur/cakupan snapshot dan progres refresh), "
            "refresh (unduh ulang data universe di latar belakang, beberapa menit), "
            "presets (daftar setup + fitur yang bisa dipakai di kriteria)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "refresh", "presets"], "default": "status"},
                "limit": {"type": "integer", "description": "Hanya untuk uji: batasi jumlah ticker saat refresh"},
            },
        },
    )


def _err(code: str, message: str, suggestion: str | None = None) -> dict:
    return {"error": True, "code": code, "message": message, **({"suggestion": suggestion} if suggestion else {})}


async def screen_stocks(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            engine.screen_current,
            presets=args.get("presets"), criteria=args.get("criteria"), match=args.get("match", "any"),
            filters=args.get("filters"), sort_by=args.get("sort_by", "value_est"),
            order=args.get("order", "desc"), clean=bool(args.get("clean", True)), limit=min(int(args.get("limit", 100)), 500),
            offset=int(args.get("offset", 0)), include_failed=bool(args.get("include_failed", False)),
        )
    except (RuleError, ValueError) as e:
        return _err("INVALID_PARAMETER", str(e))
    except Exception as e:  # noqa: BLE001
        return _err("SCREENING_ERROR", f"Gagal menjalankan screening: {e}")


async def screening_data(args: dict[str, Any]) -> dict[str, Any]:
    action = args.get("action", "status")
    try:
        if action == "presets":
            data = engine.load_presets()
            return {
                "version": data["version"], "note": data.get("note"),
                "presets": {k: {"description": v["description"], "rule": v["rule"]} for k, v in data["presets"].items()},
                "features": FEATURE_DOC,
            }
        if action == "refresh":
            started = engine.start_refresh_background(limit=args.get("limit"))
            return {"started": started, "message": "Refresh berjalan di latar belakang; cek action=status."
                    if started else "Refresh sedang berjalan.", **engine.status()}
        if action == "status":
            return engine.status()
        return _err("INVALID_PARAMETER", f"action tidak dikenal: {action}")
    except UniverseError as e:
        return _err("UNIVERSE_ERROR", str(e))
    except Exception as e:  # noqa: BLE001
        return _err("SCREENING_ERROR", str(e))
