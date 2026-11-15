
"""Cloud entry point for IDX Stock MCP on Render."""

import os
import logging
import contextlib
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

# Health check endpoint
async def health_check(request):
    return JSONResponse({
        "status": "ok",
        "service": "IDX Stock MCP",
    })

# ASGI handler
async def handle_streamable_http(
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    await session_manager.handle_request(scope, receive, send)

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
        Mount("/mcp", app=handle_streamable_http),
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
