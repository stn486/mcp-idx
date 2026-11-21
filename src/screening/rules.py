"""Evaluator aturan deklaratif (JSON).

Sintaks:
  {"all": [node, ...]}  semua harus benar
  {"any": [node, ...]}  minimal satu benar
  {"feature": "rsi14", "op": "between", "value": [40, 55]}
  {"feature": "close", "op": ">", "value": "ema20"}      # value boleh nama fitur
Operator: > >= < <= == != between
Fitur bernilai None (data tidak ada) membuat kondisi salah, tidak pernah lolos diam-diam.
"""

from __future__ import annotations

from typing import Any

OPS = {
    ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b, "!=": lambda a, b: a != b,
}


class RuleError(ValueError):
    pass


def validate(node: Any, known_features: set[str]) -> None:
    if not isinstance(node, dict):
        raise RuleError("Node aturan harus objek")
    if "all" in node or "any" in node:
        key = "all" if "all" in node else "any"
        items = node[key]
        if not isinstance(items, list) or not items:
            raise RuleError(f"'{key}' harus list tidak kosong")
        for child in items:
            validate(child, known_features)
        return
    feat, op, val = node.get("feature"), node.get("op"), node.get("value")
    if feat not in known_features:
        raise RuleError(f"Fitur tidak dikenal: {feat!r}")
    if op == "between":
        if not (isinstance(val, list) and len(val) == 2 and all(isinstance(x, (int, float)) for x in val)):
            raise RuleError("'between' butuh value [min, max] numerik")
    elif op in OPS:
        if isinstance(val, str):
            if val not in known_features:
                raise RuleError(f"Fitur pembanding tidak dikenal: {val!r}")
        elif not isinstance(val, (int, float)) or isinstance(val, bool):
            raise RuleError("value harus angka atau nama fitur")
    else:
        raise RuleError(f"Operator tidak dikenal: {op!r}")


def evaluate(node: dict, feats: dict, used: dict | None = None) -> bool:
    """Evaluasi node; nilai fitur yang dipakai kondisi benar dicatat di `used`."""
    if used is None:
        used = {}
    if "all" in node:
        local: dict = {}
        ok = all(evaluate(n, feats, local) for n in node["all"])
        if ok:
            used.update(local)
        return ok
    if "any" in node:
        for n in node["any"]:
            local = {}
            if evaluate(n, feats, local):
                used.update(local)
                return True
        return False
    a = feats.get(node["feature"])
    if a is None:
        return False
    op, val = node["op"], node["value"]
    if op == "between":
        ok = val[0] <= a <= val[1]
    else:
        b = feats.get(val) if isinstance(val, str) else val
        if b is None:
            return False
        ok = OPS[op](a, b)
    if ok:
        used[node["feature"]] = a
        if isinstance(val, str):
            used[val] = feats.get(val)
    return ok


def used_features(node: dict) -> set[str]:
    """Semua nama fitur yang dirujuk sebuah aturan (termasuk sisi kanan bila berupa fitur)."""
    if "all" in node or "any" in node:
        out: set[str] = set()
        for child in node.get("all", node.get("any")):
            out |= used_features(child)
        return out
    out = {node["feature"]}
    if isinstance(node.get("value"), str):
        out.add(node["value"])
    return out
