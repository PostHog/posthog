from __future__ import annotations

MCP_PORT = 18787
"""Non-default port to avoid conflicts with a running dev MCP server."""

SKILL_ARCHIVE_PORT = 18788
"""Local HTTP server for the working-tree skill archive consumed by MCP."""

DJANGO_LIVE_PORT = 18000
"""Non-default port for the in-process Django server."""

LLM_GATEWAY_PORT = 13308
"""Non-default port to avoid conflicts with a running dev LLM gateway."""

NGROK_WEB_PORT = 14040
"""Dedicated ngrok agent API port, so the harness never adopts or collides with
a developer's already-running ngrok agent on the default 4040."""

PERSONHOG_REPLICA_PORT = 15051
"""Non-default port so a dev-stack personhog-replica on 50051 never collides."""

PERSONHOG_ROUTER_PORT = 15052
"""Non-default port; the harness points PERSONHOG_ADDR at this router."""
