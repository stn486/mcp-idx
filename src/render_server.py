"""Cloud entry point for IDX Stock MCP on Render.

Dasar: versi produksi yang sudah berjalan (Streamable HTTP, json_response=True, Mount /mcp).
Tambahan: /admin/status dan /admin/refresh (Bearer) serta refresh snapshot screening otomatis.
"""

import os
import logging
import contextlib
from collections.abc import AsyncIterator

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route
from starlette.responses import JSONResponse
from starlette.types import Scope, Receive, Send

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from src.http_auth import check_bearer
from src.screening import engine
from src.screening.scheduler import AutoRefresher
from src.server import server

logger = logging.getLogger(__name__)

# Create Streamable HTTP session manager
session_manager = StreamableHTTPSessionManager(
    app=server,
    json_response=True,
)
auto_refresher = AutoRefresher()


def _denied(authorization: str):
    ok, status, message = check_bearer(authorization, os.environ.get("IDX_MCP_API_KEY", ""))
    if ok:
        return None
    if status == 503:
        logger.error("IDX_MCP_API_KEY is not configured")
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse({"error": message}, status_code=status, headers=headers)


# Public health check endpoint
async def health_check(request):
    return JSONResponse({
        "status": "ok",
        "service": "IDX Stock MCP",
    })


# Status snapshot screening (Bearer)
async def admin_status(request: Request):
    return _denied(request.headers.get("authorization", "")) or JSONResponse(engine.status())


# Mulai refresh snapshot di latar belakang (Bearer)
async def admin_refresh(request: Request):
    denied = _denied(request.headers.get("authorization", ""))
    if denied:
        return denied
    started = engine.start_refresh_background()
    return JSONResponse({"started": started, "already_running": not started, "status": engine.status()})


# Original MCP handler
async def handle_streamable_http(
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    await session_manager.handle_request(scope, receive, send)


# Authenticate MCP requests
async def authenticated_mcp(
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    headers = dict(scope.get("headers", []))
    denied = _denied(headers.get(b"authorization", b"").decode("latin-1"))
    if denied is not None:
        await denied(scope, receive, send)
        return

    await handle_streamable_http(scope, receive, send)


# Manage session lifecycle
@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    auto_refresher.start()
    try:
        async with session_manager.run():
            logger.info("IDX Stock MCP HTTP server started")
            yield
    finally:
        auto_refresher.stop()


# Create Starlette application
app = Starlette(
    routes=[
        Route("/health", endpoint=health_check, methods=["GET"]),
        Route("/admin/status", endpoint=admin_status, methods=["GET"]),
        Route("/admin/refresh", endpoint=admin_refresh, methods=["GET", "POST"]),
        Mount("/mcp", app=authenticated_mcp),
    ],
    lifespan=lifespan,
)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        log_level="info",
    )
