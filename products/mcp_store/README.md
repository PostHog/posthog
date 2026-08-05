# MCP store

A curated marketplace of third-party MCP servers (Linear, Notion, Sentry, ...) that users browse and connect from Settings → MCP servers (behind the `MCP_SERVERS` feature flag).
Connected servers are consumed by agent surfaces via the `backend/facade/` package.

This is unrelated to `products/*/mcp/tools.yaml`, which exposes PostHog's own endpoints as MCP tools.

## Settings experience and rollout

Two independent feature flags gate two surfaces — neither flag depends on the other:

- The Settings → MCP servers page is gated by the `mcp-servers` feature flag (`MCP_SERVERS`).
  On that page, the `mcp-gateway` feature flag (`MCP_GATEWAY`) selects the gateway experience described below; when it is off, Settings renders the existing marketplace UI.
- The standalone gateway scene at `/mcp-servers` and its nav entry are gated solely by `mcp-gateway` and are reachable even with `mcp-servers` off.

Keep both layers until the legacy `mcp-servers` flag and marketplace logic are removed in a follow-up change.

The gateway experience has these pages and workflows:

- **MCP servers**: Browse the catalog, search by server details, filter by category, and see connection status.
  Users with permission can add a hosted custom server and choose OAuth or API key authentication.
  Admins can set its team availability, and eligible users can grant initial agent access.
  Connecting starts the appropriate authorization flow, while an existing connection opens its configuration.
- **Server details**: Manage a personal connection by enabling, reconnecting, disconnecting, or removing it.
  Admins can also manage team and member access.
  Agent access can be granted or revoked with a per-tool policy, and tool policies can be searched, changed individually, or changed in bulk.
  Tool discovery can be refreshed from the connected server.
  Tool descriptions and input schemas are available for inspection, while organization rules remain locked.
- **Team and agents**: Search agents and members, inspect their access at a glance, and open a detail page.
  Agent details show identity, shared servers, per-server policies, and recent calls.
  Member details show connection and access status across registered servers, with admin controls for enabling or disabling access.
- **Team settings**: Control whether members can add custom servers or manage agent access.
  Admins can also configure member and agent policy baselines, enable or disable servers for the team, and manage organization rules.
- **Audit log**: Project admins can review all gateway activity. Members can review calls made through their own connections, including calls made by agents using connections they shared. The log supports quick filters, agent caller filters, and pagination.

The standalone gateway routes under `/mcp-servers` use the same data and page components.
When `MCP_GATEWAY` is off, the top-level scene renders a "not enabled" banner in place, while the detail routes (wrapped in `GatewayRouteGuard`) redirect to the Settings page.
Server details are available to members, while agent and member details require project admin access — the guard sends non-admins back to the gateway home.
The flag gates the frontend only: the gateway REST API has no flag check and stays reachable when the flag is off.
Settings supplies its own navigation shell so the gateway workflows fit the main PostHog application without importing the PostHog Code layout.

## How the catalog works

The catalog is **code**: `backend/catalog.py` holds one `CatalogEntry` per server.
At app startup, every environment queues `sync_mcp_server_templates` (see `backend/tasks/tasks.py`, queued from `backend/apps.py`), which upserts entries into `MCPServerTemplate` rows:

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

## What can and can't be added

Only **hosted (remote) MCP servers** on a public HTTPS endpoint speaking the streamable-HTTP transport belong in the catalog.

Adds and auto-activates on merge:

- OAuth servers with Dynamic Client Registration — the probe mints a real DCR client and verifies the authorization page.
- API-key and unauthenticated servers that answer the MCP initialize handshake without credentials.

Adds but ships **inactive** until an operator finishes activation (see the runbook below):

- OAuth servers without DCR ("shared creds") — someone must register an OAuth app with the vendor and provision credentials per environment.
- Vendors whose DCR is gated (initial access token, software statement, partner allowlist) — the probe classifies these as shared-creds too.
- API-key servers that auth-wall the handshake — a bare 401/403 carries no MCP evidence, so an operator vets and flips them active in admin (nothing to provision; users bring their own key).

Can't be added:

- Local/stdio servers (npx or docker packages with no hosted endpoint).
- Servers that aren't publicly reachable — private IPs, VPN-only hosts, and internal domains are blocked by SSRF protection.
- Non-HTTP transports (WebSocket-only) and legacy HTTP+SSE dual-endpoint servers — the probe and proxy speak streamable HTTP only.
- Any URL that fails the probe (`speaks_mcp: false`) — never ship an unprobed URL.

Known gap: API keys are sent as `Authorization: Bearer <key>`, so servers that require a custom header (`X-API-Key`, ...) or exotic auth (signed JWTs, mTLS, IP allowlists) pass the probe but fail at first real install.
A real end-to-end install (Gate B in the skill) is the only check that catches these.

## Server icons (logo.dev)

Catalog icons are not committed image assets.
Templates carry an `icon_domain` (the vendor's brand domain, e.g. `linear.app`).
The frontend renders them through the authenticated proxy endpoint `GET /api/projects/:team_id/mcp_servers/icon/?domain=<domain>&theme=<light|dark>`.
The proxy fetches each brand icon from [logo.dev](https://logo.dev) through the egress-gated `CDPIconsService`.
Logos are transparent retina PNGs matched to the active UI theme instead of logo.dev's default white-tiled JPGs.
Icon bytes are never stored on PostHog infrastructure because our logo.dev plan does not include a data-caching license.
Browsers cache responses via `Cache-Control`, and only the fact of a definitive miss is cached server-side.
Custom installations without a template derive a best-effort brand domain from their server URL.
Domains without a logo return 404 and the UI falls back to a generic server glyph.

### Self-hosted instances

Icon resolution requires a logo.dev publishable key in the `LOGO_DEV_PUBLISHABLE_KEY` environment variable and outbound network access to `img.logo.dev`.
Without the key, which is the default on self-hosted and air-gapped deployments, the icon endpoint returns 503 and the UI falls back to the generic glyph.
This is cosmetic only: installing and using MCP servers works the same without icons.
To show brand icons on a self-hosted instance, create a logo.dev account, generate a publishable key with the `pk_` prefix, and set `LOGO_DEV_PUBLISHABLE_KEY` in the web service environment.
`LOGO_DEV_TOKEN` remains a deprecated compatibility fallback for the image CDN only.

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
