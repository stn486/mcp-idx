"""IHSG di get_market_summary: terisi dari bar harian, dan gagal harus terlihat (bukan dict kosong)."""
import sys
import types

import numpy as np
import pandas as pd


def _stub_if_missing(name, **attrs):
    try:
        __import__(name)
    except ImportError:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
        if "." in name:
            parent, child = name.rsplit(".", 1)
            _stub_if_missing(parent)
            setattr(sys.modules[parent], child, mod)


def _load_market(download):
    _stub_if_missing("pytz")
    _stub_if_missing("mcp")
    _stub_if_missing("mcp.types", Tool=lambda **kw: kw)
    fake = types.ModuleType("yfinance")
    fake.download = download
    sys.modules["yfinance"] = fake
    stub = types.ModuleType("src.utils.yahoo")
    stub.yahoo_client = object()
    stub.YahooFinanceError = Exception
    sys.modules["src.utils.yahoo"] = stub
    sys.modules.pop("src.tools.market", None)
    from src.tools import market
    return market


def _frame(n=40, last_two=(5194.14, 5146.33)):
    idx = pd.bdate_range(end="2026-11-20", periods=n)
    close = np.linspace(5300, 5200, n)
    close[-2], close[-1] = last_two
    return pd.DataFrame({"Open": close, "High": close + 10, "Low": close - 10, "Close": close,
                         "Volume": np.full(n, 1e8)}, index=idx)


def test_ihsg_filled_from_daily_bars():
    m = _load_market(lambda *a, **k: _frame())
    d = m.get_ihsg_data()
    assert d["bar_date"] == "2026-11-20" and d["value"] == 5146.33
    assert d["previous_close"] == 5194.14 and d["change"] == -47.81
    assert d["change_percent"] == -0.92 and d["close_vs_ema20"] in ("di atas", "di bawah")


def test_ihsg_multiindex_columns():
    def dl(*a, **k):
        f = _frame()
        f.columns = pd.MultiIndex.from_product([f.columns, ["^JKSE"]])
        return f
    d = _load_market(dl).get_ihsg_data()
    assert d["value"] == 5146.33


def test_ihsg_failure_is_visible():
    def boom(*a, **k):
        raise RuntimeError("yahoo down")
    d = _load_market(boom).get_ihsg_data()
    assert "error" in d and "yahoo down" in d["error"]
    assert "error" in _load_market(lambda *a, **k: pd.DataFrame()).get_ihsg_data()
