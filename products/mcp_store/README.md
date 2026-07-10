# MCP Store

Connect external MCP (Model Context Protocol) servers to a PostHog project, and give agents one aggregated access point to all of them.

## Store

- **Templates** (`MCPServerTemplate`): curated catalog entries seeded by operators, optionally carrying shared OAuth client credentials. Users can also add custom servers by URL.
- **Installations** (`MCPServerInstallation`): a connected server for a team. `personal` installations belong to one user; `shared` ones are team-wide (admin-gated, executed under the installer's credential). Secrets live in an encrypted `sensitive_configuration` field and never leave the Django side.
- **Auth**: API key or OAuth. OAuth installs run discovery plus Dynamic Client Registration (or use template/user-supplied clients), with PKCE and token refresh (`oauth.py`). Refresh is single-flight per installation via a Redis lock.
- **Tools** (`MCPServerInstallationTool`): a cached catalog of each server's tools with a per-tool approval state (`approved` / `needs_approval` / `do_not_use`), synced from upstream `tools/list` (`tools.py`).
- **Proxy**: `POST /api/environments/:team_id/mcp_server_installations/:id/proxy/` forwards JSON-RPC to one server with SSRF protection, tool-approval enforcement, and credential injection (`proxy.py`).

## Gateway

The aggregated gateway (`gateway.py`) exposes every connected server through a single team-scoped surface. Resolution per caller is shared installations ∪ the caller's personal ones (enabled and credential-ready only); a personal installation shadows a shared one for the same URL. Tools are namespaced as `{server_slug}/{tool_name}`, with deterministic `-2`/`-3` suffixes on slug collisions.

Agents — external and internal — reach the gateway through the PostHog MCP (`services/mcp`), which consumes these REST endpoints (`presentation/gateway_views.py`, dual-routed under `/api/projects/` and `/api/environments/`):

- `GET .../mcp_gateway/tools/` — REST catalog with `search`, exact `name`, and `limit`/`offset`.
- `POST .../mcp_gateway/call/` — REST execution. Errors map to 403 (`tool_needs_approval` with an `approval_url`, or `tool_blocked`), 404 (`tool_not_found`), and 502 (`upstream_error` with an `error_type`).

Dispatch is one shared path: resolve → enforce approval → refresh token → SSRF check → upstream `tools/call` (`client.py`) → analytics. Every call emits a `$mcp_tool_call` event (`$mcp_source: "gateway"`; the per-installation proxy emits `$mcp_source: "store_proxy"`) with metadata only — never tool arguments, results, or credentials.

## Integration surface

Other apps may only import from `backend/facade/`:

- `get_active_installations` / `get_installations_for_sandbox` — ready-to-use installations (e.g. for sandbox agents).

An hourly Celery beat task (`maintain_shared_installations`) refreshes expiring OAuth tokens for shared installations and re-syncs tool catalogs that haven't been seen in over 24 hours.
