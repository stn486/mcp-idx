"""Pemeriksaan Bearer token tanpa dependensi (mudah diuji)."""
from __future__ import annotations

import secrets


def check_bearer(authorization: str, expected_key: str) -> tuple[bool, int, str]:
    """Kembalikan (diizinkan, status_http, pesan). Token tidak pernah dicatat/dikembalikan."""
    expected_key = (expected_key or "").strip()
    if not expected_key:
        return False, 503, "MCP authentication is not configured"
    if not secrets.compare_digest(authorization or "", f"Bearer {expected_key}"):
        return False, 401, "Unauthorized"
    return True, 200, "ok"
