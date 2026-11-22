"""Tool for getting market summary."""

from typing import Any, List, Dict
from datetime import datetime
import pytz
from mcp.types import Tool
from src.utils.yahoo import yahoo_client, YahooFinanceError
from src.utils.helpers import is_market_hours


def get_market_summary_tool() -> Tool:
    """Get market summary tool definition."""
    return Tool(
        name="get_market_summary",
        description="Mengambil ringkasan pasar (IHSG, top movers, status market).",
        inputSchema={
            "type": "object",
            "properties": {
                "include_movers": {
                    "type": "boolean",
                    "description": "Sertakan top gainers/losers (default: true)",
                    "default": True,
                },
                "movers_limit": {
                    "type": "integer",
                    "description": "Jumlah top movers (default: 5)",
                    "default": 5,
                },
            },
        },
    )


def get_ihsg_data() -> Dict[str, Any]:
    """
    Data IHSG (^JKSE) dari bar harian.

    Memakai bar harian (bukan .info) agar tetap terisi saat bursa tutup atau akhir pekan.
    Bila gagal, hasilnya memuat "error" (bukan dict kosong) supaya penyebabnya terlihat.
    """
    try:
        import yfinance as yf
        raw = yf.download("^JKSE", period="3mo", interval="1d", auto_adjust=True, progress=False)
        if raw is None or raw.empty:
            return {"error": "Data ^JKSE kosong dari Yahoo."}
        if hasattr(raw.columns, "levels"):
            raw.columns = raw.columns.get_level_values(0)
        raw = raw.dropna(subset=["Close"])
        if len(raw) < 2:
            return {"error": "Bar ^JKSE kurang dari 2."}
        last, prev = raw.iloc[-1], raw.iloc[-2]
        close, prev_close = float(last["Close"]), float(prev["Close"])
        change = close - prev_close
        out = {
            "bar_date": raw.index[-1].strftime("%Y-%m-%d"),
            "value": round(close, 2),
            "previous_close": round(prev_close, 2),
            "change": round(change, 2),
            "change_percent": round(change / prev_close * 100, 2) if prev_close else 0,
            "open": round(float(last["Open"]), 2),
            "high": round(float(last["High"]), 2),
            "low": round(float(last["Low"]), 2),
            "volume": int(last["Volume"]) if last["Volume"] == last["Volume"] else None,
            "source": "Yahoo ^JKSE, bar harian (penutupan terakhir yang tersedia)",
        }
        closes = raw["Close"].astype(float)
        if len(closes) >= 20:
            ema20 = float(closes.ewm(span=20, adjust=False).mean().iloc[-1])
            out["ema20"] = round(ema20, 2)
            out["close_vs_ema20"] = "di atas" if close > ema20 else "di bawah"
        if len(closes) >= 6:
            out["change_5d_percent"] = round((close / float(closes.iloc[-6]) - 1) * 100, 2)
        return out
    except Exception as e:
        return {"error": f"Gagal mengambil IHSG: {e}"}


def get_top_movers(limit: int = 5) -> Dict[str, List[Dict[str, Any]]]:
    """
    Get top gainers and losers.

    Args:
        limit: Number of movers to return

    Returns:
        Dictionary with top_gainers and top_losers
    """
    # This is a simplified implementation
    # In production, you'd want to fetch from a real-time data source
    # For now, we'll use a sample of popular stocks
    popular_tickers = ["BBCA", "BBRI", "BMRI", "TLKM", "ASII", "UNVR", "ICBP", "GOTO", "BRIS", "BBNI"]

    movers = []
    for ticker in popular_tickers:
        try:
            price_data = yahoo_client.get_current_price(ticker)
            movers.append({
                "ticker": price_data["ticker"],
                "name": price_data["name"],
                "price": price_data["price"],
                "change_percent": price_data["change_percent"],
            })
        except Exception:
            continue

    # Sort by change_percent
    movers.sort(key=lambda x: x["change_percent"] if x["change_percent"] else 0, reverse=True)
    top_gainers = movers[:limit]
    top_losers = sorted(movers, key=lambda x: x["change_percent"] if x["change_percent"] else 0)[:limit]

    return {
        "top_gainers": top_gainers,
        "top_losers": top_losers,
    }


def get_most_active(limit: int = 5) -> List[Dict[str, Any]]:
    """
    Get most active stocks by volume.

    Args:
        limit: Number of stocks to return

    Returns:
        List of most active stocks
    """
    popular_tickers = ["BBCA", "BBRI", "BMRI", "TLKM", "ASII", "UNVR", "ICBP", "GOTO", "BRIS", "BBNI"]

    active = []
    for ticker in popular_tickers:
        try:
            price_data = yahoo_client.get_current_price(ticker)
            active.append({
                "ticker": price_data["ticker"],
                "name": price_data["name"],
                "volume": price_data["volume"],
                "value": price_data.get("price", 0) * price_data.get("volume", 0) if price_data.get("price") and price_data.get("volume") else None,
            })
        except Exception:
            continue

    # Sort by volume
    active.sort(key=lambda x: x["volume"] if x["volume"] else 0, reverse=True)
    return active[:limit]


async def get_market_summary(args: dict[str, Any]) -> dict[str, Any]:
    """
    Get market summary.

    Args:
        args: Dictionary with optional 'include_movers' and 'movers_limit' keys

    Returns:
        Dictionary with market summary
    """
    try:
        include_movers = args.get("include_movers", True)
        movers_limit = args.get("movers_limit", 5)

        jakarta_tz = pytz.timezone("Asia/Jakarta")
        timestamp = datetime.now(jakarta_tz).isoformat()
        market_status = "open" if is_market_hours() else "closed"

        # Get IHSG data
        ihsg_data = get_ihsg_data()

        result = {
            "timestamp": timestamp,
            "market_status": market_status,
            "next_open": None,  # Could be calculated if needed
            "ihsg": ihsg_data or {},
        }

        if include_movers:
            movers = get_top_movers(movers_limit)
            result["top_gainers"] = movers["top_gainers"]
            result["top_losers"] = movers["top_losers"]
            result["most_active"] = get_most_active(movers_limit)

        return result

    except Exception as e:
        return {
            "error": True,
            "code": "NETWORK_ERROR",
            "message": f"Gagal mengambil ringkasan pasar: {str(e)}",
        }

