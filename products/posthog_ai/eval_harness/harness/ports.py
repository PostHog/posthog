from __future__ import annotations

MCP_PORT = 18787
"""Non-default port to avoid conflicts with a running dev MCP server."""

SKILL_ARCHIVE_PORT = 18788
"""Local HTTP server for the working-tree skill archive consumed by MCP."""

DJANGO_LIVE_PORT = 18000
"""Non-default port for the in-process Django server."""

AI_GATEWAY_PORT = 18080
"""Non-default port so a dev-stack Go ai-gateway on 8080 never collides."""

AI_GATEWAY_REDIS_URL = "redis://localhost:6381/5"
"""The ai-gateway compose valkey, on its own DB index.

Django publishes the credential and team policy blobs here, and the eval gateway
reads them. Policy blobs are keyed by team id, and eval team ids overlap with dev
team ids, so DB 0, which a dev-stack gateway reads, must stay untouched."""

PERSONHOG_REPLICA_PORT = 15051
"""Non-default port so a dev-stack personhog-replica on 50051 never collides."""

PERSONHOG_ROUTER_PORT = 15052
"""Non-default port; the harness points PERSONHOG_ADDR at this router."""
