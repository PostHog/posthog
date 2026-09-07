# MCP store

A curated marketplace of third-party MCP servers (Linear, Notion, Sentry, ...) that users browse and connect from Settings → MCP servers (behind the `mcp-gateway` feature flag).
Connected servers are consumed by agent surfaces via the `backend/facade/` package.

This is unrelated to `products/*/mcp/tools.yaml`, which exposes PostHog's own endpoints as MCP tools.

## Keep the desktop UI in sync

PostHog Desktop ships its own, independently written frontend for this product — same backend, same feature flags, no shared UI code:

| This product (web app)                                | PostHog Desktop equivalent                                      |
| ----------------------------------------------------- | --------------------------------------------------------------- |
| `frontend/scene/` (marketplace)                       | `products/desktop/packages/ui/src/features/mcp-servers/`        |
| `frontend/gateway/` + `frontend/settings/` (gateway)  | `products/desktop/packages/ui/src/features/mcp-gateway/`        |
| `frontend/scene/AddCustomServerForm.tsx` (custom add) | `products/desktop/packages/ui/src/features/mcp-server-manager/` |

The implementations are parallel, not shared: web uses Kea + LemonUI, desktop uses TanStack Query + quill.
The desktop also hand-writes its gateway API types in `products/desktop/packages/api-client/src/mcp-gateway.ts` as mirrors of the serializers in `backend/presentation/gateway_views.py`.

The MCP store feature set always changes for both apps together.
When you change the frontend here — a new workflow, control, state, or flag gate — make the equivalent change in the desktop features above in the same PR, or open an explicitly linked follow-up.
When you change a serializer the gateway UI consumes, update the desktop's hand-written mirrors too.

## Settings experience and rollout

The `mcp-gateway` feature flag (`MCP_GATEWAY`) gates both surfaces:

- The Settings → MCP servers page, which renders the gateway experience described below.
- The standalone gateway scene at `/mcp-servers` and its nav entry.

The marketplace UI that `McpStoreSettings` falls back to when the flag is off is unreachable, since the Settings section itself requires the flag; remove it together with the rest of the marketplace logic in a follow-up change.

The gateway experience has these pages and workflows:

- **MCP servers**: Browse the catalog, search by server details, filter by category, and see connection status.
  Users with permission can add a hosted custom server and choose OAuth or API key authentication.
  The server keeps that choice: a teammate who connects later follows it, so a server added with an API key asks each member for their own key instead of starting an OAuth flow.
  Connecting to a registered custom server is not gated by the "members can add custom servers" setting.
  Admins can set its team availability.
  Every connection is shared with the built-in PostHog agents automatically when the connecting user may manage agent access (admins always, members while team settings allow it).
  The built-in agents are the support agent, the scout agent, and the workflow agent, which runs the "Create AI task" step of a workflow; a step picks among the servers shared with the whole project, the same way a scout does.
  An agent added to the catalog later inherits the grants its siblings already hold on the team the first time it is synced.
  The add-server form picks how far that share reaches: only the user's own runs (the default), or every agent run in the project.
  Connecting a catalog server shares it for the user's own runs; the server page widens it to the team or revokes it.
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
Settings supplies its own navigation shell so the gateway workflows fit the main PostHog application without importing the PostHog Desktop layout.

## How the catalog works

The catalog is **code**: `backend/catalog.py` holds one `CatalogEntry` per server.
At app startup, every environment queues `sync_mcp_server_templates` (see `backend/tasks/tasks.py`, queued from `backend/apps.py`), which upserts entries into `MCPServerTemplate` rows:

- Rows are keyed on `url`. New entries are created; existing rows get **content fields** updated (name, description, auth type, category, icon, docs URL, OAuth scope allowlist, and credential source). The catalog owns content. Edit it in code, not admin.
- **Operational state normally stays operator-owned**: the sync preserves `is_active`, `oauth_credentials`, and `oauth_metadata` after creation unless an auth change or suspension must fail closed. A catalog-managed credential source is the exception: sync activates it after a successful shared-client probe and deactivates it when its required settings disappear. Rows absent from the catalog remain untouched.
- **Activation gate**: a newly created entry is probed live (`backend/probe.py` — MCP initialize handshake, OAuth metadata discovery, a real DCR registration, authorization-endpoint liveness). It is born active only when the probe passes for the auth model the catalog declares. A reviewed instance credential source can satisfy the shared-client gate without copying secrets into the template.
- **Temporary suspension**: `disabled=True` keeps a catalog entry inactive and deactivates an existing row on the next sync. Removing it lets a configured credential source retry its shared-client probe; other entries still require operator review.
- Probes run **only on creation**, except when a configured credential source is inactive or first adopted. DCR probes never repeat because they mint real clients.

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
- OAuth servers backed by a configured, catalog-reviewed instance credential source — the probe verifies the shared client and authorization page.
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

### Internal endpoint escape hatch

Cloud operators can allow a small number of private Streamable HTTP endpoints
for internal dogfooding with the `MCP_STORE_INTERNAL_ALLOWED_URLS_BY_TEAM`
environment variable. Its value is a JSON object keyed by team ID; every entry
must be a complete MCP URL, for example:

```text
MCP_STORE_INTERNAL_ALLOWED_URLS_BY_TEAM={"2":["http://grafana-mcp.monitoring.svc.cluster.local/mcp"]}
```

Matching is byte-for-byte and team-scoped. Configuring an endpoint does not
allow another team, path, host, port, trailing-slash variant, or any other
private address. Requests to an allowed endpoint bypass the process HTTP proxy on this MCP-only code path so
cluster-local traffic is not sent to Smokescreen; the process-wide `NO_PROXY`
configuration is unchanged.

This setting only makes the endpoint reachable. Operators must separately
restrict it with a NetworkPolicy and application authentication, and create the
internal installation explicitly. Internal endpoints do not belong in
`backend/catalog.py` and are never made visible in the public marketplace.

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
- **OAuth with an instance credential source**: a catalog entry can reuse a client already configured for that PostHog environment. The template stores only the source name; installs resolve the current credentials at runtime, so rotation does not create another secret copy. Each source pins its trusted issuer, authorization endpoint, and token endpoint before any secret leaves PostHog.
- **OAuth without DCR** ("shared creds"): an operator registers one OAuth app with the vendor and pastes `client_id`/`client_secret` into Django admin (stored encrypted per template). The sync pre-fills `oauth_metadata` from discovery; installs then share the client while each user gets their own tokens. Redirect URI: `{SITE_URL}/api/mcp_store/oauth_redirect/`.
- **API key**: users supply their own key at install; nothing on the template.

OAuth catalog entries can set `oauth_scope_allowlist` to limit registration and authorization to reviewed scopes. Without an allowlist, the client requests every scope advertised by the server. Shared clients derive their token endpoint authentication method from discovered metadata unless `oauth_credentials.token_endpoint_auth_method` overrides it.

Slack uses the existing `SLACK_APP_CLIENT_ID` and `SLACK_APP_CLIENT_SECRET` instance settings. Its catalog entry remains suspended until the production Slack app supports MCP and its regional callbacks are live. After the suspension is removed, catalog sync activates Slack only when both settings exist and the shared-client probe passes. Each Desktop user still completes a separate OAuth grant for the catalog's reviewed MCP scopes.

## Operator runbook: activating a manually provisioned shared-creds server

1. Register these redirect URIs in the vendor's developer console:
   - `https://us.posthog.com/api/mcp_store/oauth_redirect/`
   - `https://eu.posthog.com/api/mcp_store/oauth_redirect/`
2. Request only the scopes in the catalog entry's `oauth_scope_allowlist` and complete any provider review.
3. Django admin → MCP server templates → the server: paste client ID and client secret.
4. Confirm the discovered metadata and token endpoint authentication method. Run the "Discover metadata" admin action if metadata is empty.
5. Complete one internal authorization and tool discovery in each environment.
6. Tick "is active". Repeat per environment because templates are per-database rows.

If the catalog entry has `disabled=True`, remove the suspension in a follow-up only after these checks pass. Removing the suspension does not reactivate a manually provisioned row.

## Reaching connected servers from an agent

There are two ways a caller uses a connection, and they differ in who speaks MCP.

- **`POST .../mcp_server_installations/:id/proxy/`** is a transparent JSON-RPC passthrough.
  The caller is an MCP client that runs its own `initialize` handshake and holds the session — PostHog Desktop points a sandbox at this URL as if it were the vendor's server.
  Built-in agents get the equivalent root-level route with a signed token (see `backend/facade/api.py`).
- **`POST .../mcp_server_installations/:id/call_tool/`** takes `{tool_name, arguments}` and returns one tool result.
  The caller wants a result, not a transport, so PostHog runs the handshake server-side (`call_upstream_tool` in `backend/tools.py`).
  This is what the PostHog MCP's `exec` uses, so an external agent (Claude Code, Codex) can call a connected server's tools through its existing PostHog connection instead of authenticating each vendor separately.
  Discovery for that path is `GET .../mcp_server_installations/available_tools/`, which returns every callable tool across the caller's connections in one request, each namespaced by a server slug (`linear__create_issue`).
  When two connections share a display name, both slugs carry a fragment of their installation id (`linear-a1b2c3`), and that ambiguity is decided over every connection the caller can address rather than only the reachable ones — otherwise an expiring token could re-point a tool name at a different connection between refreshes.
  The `exec` side lives in `services/mcp/src/lib/gateway-tools.ts` and is gated on the `mcp-gateway` flag.

Agents mount a connection without connecting to it, so an installation's `description` (copied from the catalog entry at install time) travels with the server config and is what the agent's tool search matches on until the first call.
A connection with no description is only findable by searching its exact name.
Cloud runs read it through `get_installations_for_sandbox`, which falls back to the template's description; desktop runs read it from the installation serializer.
Either way the description is for pi only, so the agent server drops it before passing servers to claude or codex.

Both paths resolve policy through the same `resolve_call_decision` / `_gateway_decision` in `backend/proxy.py` and write the same `MCPAuditEvent` rows, so approval state and the audit trail cannot diverge between them.
`needs_approval` and `do_not_use` tools are refused before any upstream request.

## Key modules

| Path                                   | What it is                                                                      |
| -------------------------------------- | ------------------------------------------------------------------------------- |
| `backend/catalog.py`                   | The curated catalog (source of truth for content)                               |
| `backend/catalog_sync.py`              | Upsert + probe-gated activation semantics                                       |
| `backend/probe.py`                     | Live server verification, up to the OAuth consent screen                        |
| `backend/models.py`                    | `MCPServerTemplate`, `MCPServerInstallation` (+ per-install tools, OAuth state) |
| `backend/oauth.py`                     | RFC 9728/8414 discovery, RFC 7591 DCR, token exchange/refresh                   |
| `backend/proxy.py`, `backend/tools.py` | MCP request proxying, tool discovery, and single tool calls                     |
| `backend/facade/`                      | The only cross-product import surface                                           |
| `frontend/scene/`                      | Marketplace UI (`MarketplaceBrowser`, `ServerCard`, ...)                        |
