
"""Cloud entry point for IDX Stock MCP on Render."""

import os
import uvicorn

from src.server import server

# Expose the existing 26-tool MCP server over Streamable HTTP.
app = server.streamable_http_app(
    host="0.0.0.0",
)

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        log_level="info",
    )
