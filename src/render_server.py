
"""Cloud entry point for IDX Stock MCP on Render."""

import os
import logging
import contextlib
import secrets
from collections.abc import AsyncIterator

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.responses import JSONResponse
from starlette.types import Scope, Receive, Send

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from src.server import server

logger = logging.getLogger(__name__)

# Create Streamable HTTP session manager
session_manager = StreamableHTTPSessionManager(
    app=server,
    json_response=True,
)


# Public health check endpoint
async def health_check(request):
    return JSONResponse({
        "status": "ok",
        "service": "IDX Stock MCP",
    })


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
    expected_token = os.environ.get("IDX_MCP_API_KEY")

    if not expected_token:
        logger.error("IDX_MCP_API_KEY is not configured")
        response = JSONResponse(
            {"error": "MCP authentication is not configured"},
            status_code=503,
        )
        await response(scope, receive, send)
        return

    headers = dict(scope.get("headers", []))
    authorization = headers.get(b"authorization", b"").decode("latin-1")

    expected_authorization = f"Bearer {expected_token}"

    if not secrets.compare_digest(
        authorization,
        expected_authorization,
    ):
        response = JSONResponse(
            {"error": "Unauthorized"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)
        return

    await handle_streamable_http(scope, receive, send)


# Manage session lifecycle
@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with session_manager.run():
        logger.info("IDX Stock MCP HTTP server started")
        yield


# Create Starlette application
app = Starlette(
    routes=[
        Route("/health", endpoint=health_check, methods=["GET"]),
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
