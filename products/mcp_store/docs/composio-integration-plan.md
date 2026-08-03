# Adding hundreds of integrations to the MCP store with Composio

Status: proposal, not implemented.
Owner: team-self-driving (owner of `products/mcp_store`).

## Context

The MCP store ships 38 servers today, hand-curated in `backend/catalog.py`.
Every entry is a real hosted MCP endpoint on the vendor's own domain, and the store connects to it directly: OAuth discovery per RFC 9728/8414, a per-user client minted with RFC 7591 dynamic client registration, tokens stored encrypted on `MCPServerInstallation`.
That model is excellent and should not be replaced. It is also why the catalog is 38 entries and not 400.

The bottleneck is supply, not code. An entry can only ship auto-activated when the vendor runs a hosted streamable-HTTP MCP server _and_ supports DCR.
Everything else, per the README, needs an operator to register an OAuth app with the vendor by hand and paste credentials into Django admin, per environment.
That is roughly a day of human work per integration, and most SaaS vendors still have no remote MCP server at all.

[Composio](https://composio.dev) covers exactly that gap: 1,000+ toolkits and 20,000+ tools, with auth, token refresh, and a hosted MCP endpoint per user.
Wiring it in turns "one operator-day per integration" into "one catalog sync".

Two things constrain the design, and both come from the original request:

1. **Frictionless setup.** A user in Settings → MCP servers should find the app they want and be connected in one click. Today's marketplace renders every catalog entry on mount with a client-side substring filter and no pagination. That falls over at 400 entries, let alone 1,000.
2. **White-labeled connections.** The user should be connecting their Notion account to PostHog, not to Composio. How far that is achievable is the sharpest trade-off in this document, so it gets its own section.

## What Composio actually gives us, and what it costs

Verified against their docs:

- **Toolkits and tools.** REST endpoints to list toolkits, toolkit categories, a toolkits changelog, and the tools within a toolkit. This is what a catalog sync reads.
- **Auth configs** (`ac_...`), one per toolkit, either `use_composio_managed_auth` (zero setup, Composio's OAuth app) or `use_custom_auth` with our own `client_id`/`client_secret` and an optional `oauth_redirect_uri` we control. Creatable programmatically via `composio.auth_configs.create()`, so white-labeling a toolkit is a config change, not a code change.
- **Connected accounts**, keyed by a `user_id` string we choose. Composio stores and refreshes the OAuth tokens and emits a `composio.connected_account.expired` webhook when a refresh token dies.
- **Sessions with a hosted MCP endpoint.** `composio.sessions.create(user_id=..., toolkits=[slug], session_preset=SESSION_PRESET_DIRECT_TOOLS, mcp=True)` returns `session.mcp.url` and `session.mcp.headers`. With the direct-tools preset the endpoint serves exactly the tools we list and no meta or search tools, which is what our per-tool approval model needs.
- **Credential import.** Existing API keys and bearer tokens can be pushed into Composio so a user who has already connected a service somewhere in PostHog does not have to reconnect.

Costs and constraints, stated plainly because they should drive the go/no-go:

- **Metered.** Pricing is per tool call, roughly $229/month for 2M calls at the Professional tier with per-1,000 overage above that. An agent in a retry loop is a billing incident, not just a bug.
- **User data flows through a third party.** Composio holds OAuth tokens for hundreds of services on behalf of our users and sits in the data path of every tool call. That is a real concentration of risk and a subprocessor decision, not only an engineering one.
- **EU residency is unresolved.** Composio's backend is `backend.composio.dev`. Whether EU Cloud can use this at all needs a legal answer before launch. VPC and on-prem exist on their Enterprise tier.
- **Self-hosted PostHog gets nothing.** No Composio API key means no Composio toolkits. This is fine, and it is the same degradation model the store already has for logo.dev icons, but it must be a graceful absence rather than an error.
- **Availability coupling.** A Composio outage takes down every long-tail server at once. Native DCR entries are unaffected, which is a good argument for keeping both paths.

## Architecture: Composio as a second provider, not a second product

The insight that makes this cheap: from the store's perspective, a Composio toolkit is just a server whose upstream URL and auth headers are resolved at call time instead of being stored on the row.
Everything downstream of that resolution already works and should not be touched: tool approval policy, org rules, audit events, SSE streaming, gateway grants, agent service accounts, the desktop client, the facade.

### The seam

Add `backend/providers/` with one contract:

```python
@dataclass(frozen=True, kw_only=True)
class UpstreamTarget:
    url: str
    headers: dict[str, str]


def resolve_upstream(installation: MCPServerInstallation) -> UpstreamTarget: ...
```

- **Native provider** returns `UpstreamTarget(url=installation.url, headers=build_upstream_auth_headers(installation))` after `ensure_valid_token`. This is exactly today's behavior, relocated.
- **Composio provider** mints or reuses a session for `(installation)` and returns `UpstreamTarget(url=session.mcp.url, headers=session.mcp.headers)`.

Two call sites change:

- `backend/proxy.py:proxy_mcp_request` (`proxy.py:399`) resolves the target once, SSRF-validates `target.url` rather than `installation.url` (`proxy.py:407`), and passes `target.headers` into the header dict it already builds (`proxy.py:451`). The policy block, the audit write, the same-origin redirect guard, and `_build_sse_response` are all untouched.
- `backend/tools.py:fetch_upstream_tools` does the same for the `initialize` → `tools/list` handshake.

Keeping SSRF validation on the resolved URL matters: a Composio session URL is on `mcp.composio.dev`, not the vendor's domain, so the check has to move with the value rather than be skipped.

### Session lifecycle

Sessions carry our API key, so they are minted server-side and never handed to a client.
Minting one per JSON-RPC message would add a Composio round trip to every tool call, so the resolved `(url, headers)` pair is cached in Redis keyed by installation id with a TTL comfortably under the session lifetime.
A 401 from upstream invalidates the cache entry and re-mints exactly once before the request fails.
This keeps the hot path at one cache read.

### Model changes

`MCPServerTemplate` and `MCPServerInstallation` both gain:

- `provider` — `"native"` (default) or `"composio"`.
- `provider_ref` — the Composio toolkit slug, blank for native rows.

Templates additionally get `composio_auth_config_id` so a white-labeled toolkit can point at our own auth config.
Installations store the Composio connected account id inside the existing encrypted `sensitive_configuration`, alongside a `provider` marker; no new plaintext identifier for a user's third-party account.

The interesting migration detail is identity.
Today `url` is unique on templates, and installations carry partial unique constraints on `(team, user, url)` for personal scope and `(team, url)` for shared.
A Composio template has no vendor MCP URL to key on.
Two options:

- Synthesize `composio://toolkit/{slug}` as the `url`. Zero constraint churn, but a fake URL leaks into serializers, the desktop client, and the SSRF-checked field. Rejected.
- Make `url` blank for Composio rows, convert the existing unique constraints to partial constraints scoped to `provider="native"`, and add matching partial constraints on `(provider, provider_ref)`. More migration work, honest data model. **Recommended.**

Follow `/django-migrations` for the constraint swap: add the new partial uniques concurrently first, then drop the old ones in a follow-up, rather than doing both in one migration.

### Catalog sync

A separate path from `catalog_sync.py`, because probing does not apply: `backend/composio/catalog_sync.py`, run from Celery beat on a daily schedule rather than from `apps.py:ready()`.
The existing startup-queued native sync stays as it is.

Curation is the part that decides whether the marketplace is useful or a junk drawer. Three tiers:

- **Tier A, white-labeled (~30 toolkits).** The apps most PostHog customers actually use: Google Workspace, Slack, GitHub, Notion, Linear, Jira, HubSpot, Salesforce, Zendesk, Intercom, Stripe, Figma. Own OAuth app, custom auth config, callback proxied through posthog.com. Hand-verified end to end.
- **Tier B, managed auth (~200–400).** Auto-activated if the toolkit passes quality gates: has a supported auth scheme, has at least one tool, is not deprecated in the changelog. Browsable by category.
- **Tier C, the long tail.** Reachable by search but not surfaced in category browsing, so the default experience stays curated while the answer to "do you support X" is still yes.

A toolkit that disappears from Composio's changelog is deactivated, never deleted, because installations point at it.
Where a vendor exists both natively and via Composio, **native wins**: the native path has no third party in the data path. The sync skips any toolkit slug that maps to an active native template.

### Connect flow

For a Composio-backed template:

1. `install_template` creates the installation row, ensures an auth config exists for the toolkit, and asks Composio for a Connect Link with `callback_url` pointing back at PostHog.
2. `MCPOAuthState` is reused for the round trip: hashed state token, `web_return_path`, `install_source`, and the `posthog-code://` desktop deep link all work unchanged. We are not doing the code exchange ourselves, so state here is purely our own CSRF and return-path carrier.
3. A new `/api/mcp_store/composio_redirect/` viewset consumes the state, confirms with Composio that the connected account is `ACTIVE`, stores the connected account id, queues `sync_installation_tools_task`, and reuses the existing `_build_oauth_redirect` logic to land the user back where they started.
4. Composio's `composio.connected_account.expired` webhook maps onto the `needs_reauth` flag the UI already renders, so expiry surfaces as the same "Reconnect" state as native servers.

### Tool listing

Two sources, used for different things:

- **Composio's tools REST API** for the catalog preview, so a server detail panel can show what an app can do before the user connects. No session, no cost.
- **The session MCP handshake** for an actual installation, because that is authoritative about what the proxy will really serve.

Toolkits are big: Gmail alone has dozens of tools, and the store defaults every newly discovered tool to `needs_approval`.
Connecting Google Workspace and being handed a 60-row approval list is the opposite of frictionless.
So a Composio installation is seeded with a curated subset enabled and the rest collapsed behind "Show all N tools".
The same subset is passed as `tools={slug: {"enable": [...]}}` when minting the session, which enforces it upstream and keeps agent context small.

### Egress and secrets

Composio is a metered third-party API, which puts it squarely in the case `posthog/egress/README.md` describes.
Add `posthog/egress/composio/` as a new domain alongside `github/` and `logodev/`: a budget policy read from settings, a metric set, and a transport subclass, so every Composio call is gated and recorded by construction.
This is also where a per-team monthly tool-call budget lives, which is the defense against a runaway agent turning into an invoice.

Settings: `COMPOSIO_API_KEY`, plus `COMPOSIO_BASE_URL` for a future VPC deployment.
Absent by default. When absent, Composio templates simply never sync and nothing in the UI mentions them.

## White-labeling: what is achievable, honestly

Composio branding shows up in four places, and they are not equally fixable.

| Surface                     | Default                                 | Fix                                                                     | Cost                                             |
| --------------------------- | --------------------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------ |
| Connect Link page           | Composio logo and name                  | Upload PostHog logo and app title in project settings                   | One-time, covers everything                      |
| OAuth consent screen        | "Composio wants to access your account" | Register our own OAuth app for that toolkit, use a custom auth config   | Per toolkit, days to weeks per vendor            |
| Address bar during redirect | `backend.composio.dev` flashes          | Proxy the callback through a posthog.com endpoint that 302s to Composio | Per toolkit, but only once the OAuth app is ours |
| Post-auth success page      | Composio-branded                        | Pass `callback_url` when creating the link                              | One-time                                         |

So: **two of the four are one-time fixes that apply to all 1,000 toolkits**, and the two that matter most to a security-conscious user (the consent screen, the address bar) require our own OAuth app with each vendor.

There is no shortcut here. Composio's own docs are explicit that the "Secured by Composio" badge only disappears when the OAuth app is yours.
Registering 1,000 OAuth apps is not a plan; several of them (Google, Slack, Salesforce) involve review processes measured in weeks.

The recommendation is therefore the tiered approach above: **white-label the ~30 toolkits that account for most connections, ship the long tail on managed auth with the PostHog-branded Connect Link, and keep expanding tier A over time.**
A user connecting Slack sees PostHog end to end. A user connecting an obscure niche tool sees a PostHog-branded page that mentions Composio on the consent screen. That is a reasonable place to land, and it is honest to the user about who holds their token.

The maximal option exists and is worth knowing about: run the OAuth flow ourselves with the store's existing machinery and push the resulting bearer token into Composio as an imported connection.
That gives full white-labeling with no Composio-hosted page at all, at the cost of owning token refresh per vendor. It is not worth it across the board, but it is the right escape hatch for any toolkit where a customer contractually requires it, and it is also how we could let a user reuse an existing PostHog `Integration` (Slack, HubSpot, Salesforce) without reconnecting.

## Frictionless UX at 400+ entries

The current marketplace is built for 38 entries and will not survive 400. Concretely, what needs to change:

**Backend.** `MCPServerViewSet.list` (`presentation/views.py:229`) is a custom unpaginated list that serializes every active template in one shot.
Give it `search`, `category`, `limit`, and `offset` params with a trigram index behind the search, keeping the `{"results": [...]}` envelope so nothing breaks.
Ranking matters more than completeness here: exact name match, then popularity (installs across the instance), then description match.

**Frontend.** `mcpStoreLogic.filteredServers` does a `toLowerCase().includes()` over the full list on every keystroke with no debounce, and `MarketplaceBrowser` renders every card in every category with an eager `<img>` per card hitting the icon proxy.
That becomes 400 concurrent proxied logo.dev requests on mount.
The fix is a search-first layout:

- A prominent debounced search box backed by the server-side endpoint.
- Above the fold: a short "Popular" rail and a "Suggested for your team" rail, not an alphabetical wall. Suggestions can be derived from what the org already has (an existing Slack `Integration`, a GitHub warehouse source), which also sets up the "reuse your existing connection" path.
- Category chips with counts, matching what the gateway surface already does.
- Lazy icon loading and a virtualized list for search results.

**Connect stays one click.** Card → connect → full-page redirect to the PostHog-branded consent flow → back to `?oauth_complete=true` with a toast. That is the flow today for OAuth templates on the gateway surface and it is the right one; nothing about Composio makes it worse.

**Two small existing rough edges worth fixing in the same pass**, since both get riskier as the catalog grows: Remove deletes an installation with no confirmation dialog, and `mcpStoreLogic` is still on the untyped `lib/api.ts` client while everything gateway-side uses the generated `products/mcp_store/frontend/generated/api.ts` (see `/adopting-generated-api-types`).

## Suggested PR breakdown

Each step is independently shippable and safe to stop after.

1. `posthog/egress/composio/` domain, settings, and a thin typed client. No user-visible change.
2. Provider seam: `backend/providers/`, `resolve_upstream`, proxy and tools routed through it. Native-only, pure refactor plus tests.
3. Migration adding `provider` / `provider_ref` / `composio_auth_config_id` and the partial unique constraints. No behavior change.
4. Composio provider implementation: session minting, Redis cache, `resolve_upstream`. Gated on `COMPOSIO_API_KEY` being present.
5. Catalog sync with the tier gates and a Celery beat schedule. Templates ship inactive.
6. Connect flow: Connect Link creation, `composio_redirect` viewset, expiry webhook, tool sync.
7. Catalog API: server-side search, pagination, ranking.
8. Frontend: search-first marketplace, lazy icons, curated tool subset UI.
9. White-labeling pass: custom auth configs for tier A, callback proxy endpoint, Connect Link branding.
10. Per-team quotas, admin surfaces, docs, and a README update.

## Decisions needed before step 1

These are not engineering choices and they gate the work:

- **EU Cloud.** Does user data through `backend.composio.dev` clear our residency commitments, or does EU launch wait on a VPC deployment? If the answer is "wait", steps 1–8 still ship, gated per region.
- **Subprocessor and DPA.** Composio holding customer OAuth tokens needs the usual paperwork and a public subprocessor listing.
- **Plan gating.** Metered tool calls mean this probably should not be unlimited on the free tier. Decide whether Composio-backed servers are a paid feature, a quota'd one, or both.
- **Tier A list.** Which ~30 toolkits get our own OAuth app first, since each one is real vendor-registration work.

## Verification

- Unit: provider seam resolution for both providers; catalog sync tier gating and deactivation; session cache invalidation on 401.
- Integration: `products/mcp_store/backend/test/test_proxy.py` extended with a Composio-backed installation, asserting policy enforcement and audit writes are identical to native.
- Manual: `hogli start`, feature flag on, `COMPOSIO_API_KEY` set against a Composio dev project. Connect a toolkit from Settings → MCP servers, confirm the round trip lands back on the settings page, tools populate, a `tools/call` proxies and is audited, and a blocked tool returns `-32002`.
- Check the same installation is reachable from PostHog Desktop and from an agent service account grant, since both consume the facade rather than the views.
