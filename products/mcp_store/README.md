# MCP store

A curated marketplace of third-party MCP servers (Linear, Notion, Sentry, ...) that users browse and connect from Settings → MCP servers (behind the `MCP_SERVERS` feature flag).
Connected servers are consumed by agent surfaces via the `backend/facade/` package.

This is unrelated to `products/*/mcp/tools.yaml`, which exposes PostHog's own endpoints as MCP tools.

## How the catalog works

The catalog is **code**: `backend/catalog.py` holds one `CatalogEntry` per server.
At app startup, every environment queues `sync_mcp_server_templates` (see `backend/tasks/tasks.py` and `posthog/apps.py`), which upserts entries into `MCPServerTemplate` rows:

- Rows are keyed on `url`. New entries are created; existing rows get **content fields** updated (name, description, auth_type, category, icon_domain, docs_url). The catalog owns content — edit it in code, not admin.
- **Operational state is never touched by the sync**: `is_active` after creation, `oauth_credentials`, and `oauth_metadata` once set belong to the row and to operators. Rows absent from the catalog (e.g. admin-added) are left alone.
- **Activation gate**: a newly created entry is probed live (`backend/probe.py` — MCP initialize handshake, OAuth metadata discovery, a real DCR registration, authorization-endpoint liveness). It is born active only when the probe passes for the auth model the catalog declares. Servers that need shared OAuth credentials (no DCR) are born inactive until an operator provisions them.
- Probes run **only on creation** — a DCR probe mints a real client on the provider, so re-probing every sync would leak registrations.

To add a server, follow the `adding-mcp-store-servers` skill (`.agents/skills/adding-mcp-store-servers/`).
To probe a server by hand:

```sh
DEBUG=1 python manage.py probe_mcp_server https://mcp.example.com/mcp
DEBUG=1 python manage.py sync_mcp_server_templates --skip-probe  # local seed without network
```

## Icons

Templates carry an `icon_domain` (the vendor's brand domain, e.g. `linear.app`).
The frontend renders `GET /api/projects/:id/mcp_servers/icon/?domain=<icon_domain>`, which proxies logo.dev through `CDPIconsService` (cached, egress-gated — see `posthog/egress/logodev/`).
No image assets are committed; custom installs without a template derive a best-effort domain from their server URL.
Unknown domains fall back to a generic server icon.

## Auth models

- **OAuth with DCR** (most modern remote servers): nothing to provision. Each install discovers OAuth metadata fresh and mints a per-user client via RFC 7591. Template `oauth_credentials`/`oauth_metadata` stay empty.
- **OAuth without DCR** ("shared creds"): an operator registers one OAuth app with the vendor and pastes `client_id`/`client_secret` into Django admin (stored encrypted per template). The sync pre-fills `oauth_metadata` from discovery; installs then share the client while each user gets their own tokens. Redirect URI: `{SITE_URL}/api/mcp_store/oauth_redirect/`.
- **API key**: users supply their own key at install; nothing on the template.

## Operator runbook: activating a shared-creds server

1. Register an OAuth app in the vendor's developer console with redirect URI `https://us.posthog.com/api/mcp_store/oauth_redirect/` (repeat for EU with the EU host).
2. Django admin → MCP server templates → the server: paste client ID and client secret.
3. `oauth_metadata` should already be populated by the sync; if empty, run the "Discover metadata" admin action.
4. Tick "is active". Repeat per environment — templates are per-database rows.

## Key modules

| Path                                   | What it is                                                                      |
| -------------------------------------- | ------------------------------------------------------------------------------- |
| `backend/catalog.py`                   | The curated catalog (source of truth for content)                               |
| `backend/catalog_sync.py`              | Upsert + probe-gated activation semantics                                       |
| `backend/probe.py`                     | Live server verification, up to the OAuth consent screen                        |
| `backend/models.py`                    | `MCPServerTemplate`, `MCPServerInstallation` (+ per-install tools, OAuth state) |
| `backend/oauth.py`                     | RFC 9728/8414 discovery, RFC 7591 DCR, token exchange/refresh                   |
| `backend/proxy.py`, `backend/tools.py` | MCP request proxying and tool discovery                                         |
| `backend/facade/`                      | The only cross-product import surface                                           |
| `frontend/scene/`                      | Marketplace UI (`MarketplaceBrowser`, `ServerCard`, ...)                        |
