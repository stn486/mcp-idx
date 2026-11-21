"""Versi vektor dari rules.evaluate: satu boolean per tanggal. Dipakai backtest."""

from __future__ import annotations

import operator

import pandas as pd

_OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le,
        "==": operator.eq, "!=": operator.ne}


def evaluate_frame(node: dict, df: pd.DataFrame) -> pd.Series:
    """Semantik sama dengan rules.evaluate; nilai NaN (data tidak ada) selalu salah."""
    if "all" in node:
        out = pd.Series(True, index=df.index)
        for n in node["all"]:
            out &= evaluate_frame(n, df)
        return out
    if "any" in node:
        out = pd.Series(False, index=df.index)
        for n in node["any"]:
            out |= evaluate_frame(n, df)
        return out
    a = df[node["feature"]]
    op, val = node["op"], node["value"]
    if op == "between":
        return (a >= val[0]) & (a <= val[1])
    if isinstance(val, str):
        b = df[val]
        return _OPS[op](a, b) & a.notna() & b.notna()
    return _OPS[op](a, val) & a.notna()
