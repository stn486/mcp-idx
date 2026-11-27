"""Tool MCP: get_levels (level harga mentah per ticker) dan calc_risk_reward (kalkulator R/R bersih)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from mcp.types import Tool

from src.screening import levels as lv
from src.screening.calendar import trading_dates
from src.utils.yahoo import yahoo_client, YahooFinanceError


def get_levels_tool() -> Tool:
    return Tool(
        name="get_levels",
        description=(
            "Level harga MENTAH satu ticker dari data harian (tersedia juga saat bursa tutup; bukan harga live): "
            "swing high/low terkonfirmasi (beberapa terakhir, dengan tanggal), low 5/10/20 hari, high 20/60 hari, "
            "Fibonacci (retracement dan extension) dari swing terakhir, pivot standar dari sesi terakhir, gap yang belum tertutup, "
            "dan jarak tiap level ke close dalam satuan ATR14 (dist_atr, negatif = di bawah close). "
            "Tidak memberi rekomendasi entry/SL/TP dan tidak menyaring kandidat; memilih level adalah tugas pemanggil. "
            "Cek field data.current dan data.last_bar_partial sebelum memakai angkanya."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Ticker IDX, mis. BBRI"},
                "pivot_bars": {"type": "integer", "default": 2, "minimum": 1, "maximum": 10,
                               "description": "Pengapit swing: jumlah bar kiri dan kanan"},
                "swing_count": {"type": "integer", "default": 5, "minimum": 1, "maximum": 15,
                                "description": "Berapa swing terakhir ditampilkan per sisi"},
            },
            "required": ["ticker"],
        },
    )


def calc_risk_reward_tool() -> Tool:
    return Tool(
        name="calc_risk_reward",
        description=(
            "Kalkulator R/R bersih posisi beli (aritmetika pasti, bukan perkiraan). Semua biaya dan batas berasal dari input; "
            "tidak ada nilai bawaan. profit = (TP-entry) - fee_buy*entry - fee_sell*TP; rugi = (entry-SL) + fee_buy*entry + fee_sell*SL. "
            "Jika modal, risk_pct, alloc_pct diisi, dihitung lot (min dari lot risiko dan lot alokasi, bulat ke bawah). "
            "min_rr opsional: harga entry tertinggi (kelipatan fraksi BEI) yang masih memenuhi R/R bersih tersebut."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "entry": {"type": "number"}, "sl": {"type": "number"}, "tp": {"type": "number"},
                "entry_high": {"type": "number", "description": "Batas atas area entry (opsional, dihitung terpisah)"},
                "fee_buy_pct": {"type": "number", "default": 0, "description": "Persen, mis. 0.15"},
                "fee_sell_pct": {"type": "number", "default": 0, "description": "Persen, mis. 0.25"},
                "slippage_ticks_entry": {"type": "integer", "default": 0},
                "slippage_ticks_sl": {"type": "integer", "default": 0},
                "modal": {"type": "number"}, "risk_pct": {"type": "number", "description": "Risiko maks per trade, % modal"},
                "alloc_pct": {"type": "number", "description": "Alokasi maks per posisi, % modal"},
                "one_lot_max_alloc_pct": {"type": "number", "description": "Pengecualian: 1 lot boleh sampai % modal ini jika risiko tetap dalam batas"},
                "min_rr": {"type": "number"},
            },
            "required": ["entry", "sl", "tp"],
        },
    )


def _err(code: str, message: str, suggestion: str | None = None) -> dict:
    return {"error": True, "code": code, "message": message, **({"suggestion": suggestion} if suggestion else {})}


def _to_df(hist: dict) -> pd.DataFrame:
    df = pd.DataFrame(hist["data"])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")[["open", "high", "low", "close", "volume"]]


def _levels_sync(ticker: str, pivot_bars: int, swing_count: int) -> dict:
    hist = yahoo_client.get_historical_data(ticker, period="1y", interval="1d")
    df = _to_df(hist)
    out = lv.compute_levels(df, pivot_bars=pivot_bars, swing_count=swing_count)
    status = lv.data_status(out["last_bar_date"], datetime.now(timezone.utc), trading_dates())
    warnings = []
    if not status["current"]:
        warnings.append(f"Bar terakhir {out['last_bar_date']} lebih lama dari penutupan yang diharapkan {status['expected_bar_date']}; level mungkin basi.")
    if status["last_bar_partial"]:
        warnings.append("Bar hari ini belum final (bursa belum tutup); high/low/close dan ATR bisa berubah.")
    return {"ticker": hist["ticker"], "data": {**status, **out}, "warnings": warnings}


async def get_levels(args: dict[str, Any]) -> dict[str, Any]:
    ticker = str(args.get("ticker", "")).upper().strip()
    if not ticker:
        return _err("INVALID_PARAMETER", "ticker wajib diisi")
    try:
        return await asyncio.to_thread(_levels_sync, ticker, int(args.get("pivot_bars", 2)), int(args.get("swing_count", 5)))
    except ValueError as e:
        return _err("INVALID_PARAMETER", str(e))
    except YahooFinanceError as e:
        return _err("DATA_UNAVAILABLE", str(e), "Pastikan ticker valid")
    except Exception as e:  # noqa: BLE001
        return _err("LEVELS_ERROR", f"Gagal menghitung level: {e}")


async def calc_risk_reward(args: dict[str, Any]) -> dict[str, Any]:
    keys = ("entry_high", "fee_buy_pct", "fee_sell_pct", "slippage_ticks_entry", "slippage_ticks_sl",
            "modal", "risk_pct", "alloc_pct", "one_lot_max_alloc_pct", "min_rr")
    try:
        kw = {k: args[k] for k in keys if args.get(k) is not None}
        return lv.calc_risk_reward(args.get("entry"), args.get("sl"), args.get("tp"), **kw)
    except (ValueError, TypeError) as e:
        return _err("INVALID_PARAMETER", str(e))
