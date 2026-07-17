# Staff support MCP tools: setup guide

The managed migrations support tools let PostHog staff triage customer batch imports (managed migrations) from any MCP client — Claude Code, Claude Desktop, Cursor — instead of Django admin.

- `managed-migrations-support-list` — list batch import jobs across **all** teams, filterable by `team_id`, `status`, or free-text search
- `managed-migrations-support-get` — one job by UUID, including the raw worker `state` and `import_config` blobs

Both are read-only.
Mutations (resume, pause, in-flight part reset) remain Django admin actions for now.
Credential values (`secrets`) are never returned by any of these surfaces, and every staff read is audit-logged.
Detail reads additionally write a `support_viewed` entry to the team's activity log, so the access is visible and queryable in-app, not only in centralized logs.

## Who can use this

PostHog staff only (`is_staff = True` on your PostHog cloud user).
Everything below fails closed for non-staff users: the tools never appear in their MCP clients, and the API returns 403 even with a correctly-scoped key.

## Step 1: mint the personal API key

The `batch_import_support:read` scope is **hidden from the key-creation UI** and can never be granted through OAuth,
so minting takes two steps — create the key normally, then add the hidden scope via Django admin:

1. In the PostHog UI on the region you want to inspect, go to **Settings → Personal API keys** and create a key with the **User: Read** scope and **no organization/project restriction** (the endpoint rejects scoped keys). Copy the `phx_...` value — it is shown only once.
2. In Django admin (`/admin/posthog/personalapikey/`), open your new key and add `batch_import_support:read` to its `scopes` list, then save. Do this **before** first using the key with MCP — the MCP server caches a token's scopes on first use.

<details>
<summary>Alternative: one-shot mint from the browser console</summary>

While logged in, on any PostHog app page:

```js
await fetch('/api/personal_api_keys/', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-Csrftoken': document.cookie.match(/posthog_csrftoken=([^;]+)/)[1],
  },
  body: JSON.stringify({ label: 'migrations support', scopes: ['batch_import_support:read', 'user:read'] }),
}).then((r) => r.json())
```

The CSRF header is required — session-authenticated POSTs are CSRF-protected.
If you get `sensitive_action_required_reauth`, key creation needs a recently-authenticated session: log out, log back in, retry.

</details>

Rules that will bite you if skipped:

- **Both scopes are required for MCP.** `batch_import_support:read` authorizes the endpoints; `user:read` lets MCP tool discovery confirm you are staff via `/api/users/@me/`. Without `user:read` the tools silently never appear (the check fails closed).
- **`*` (full access) does not work.** The backend rejects wildcard keys on this endpoint, and tool discovery requires the hidden scope to be listed explicitly.
- **The key must be unscoped** — no `scoped_teams` / `scoped_organizations`. The endpoint is root-level and cross-team by design; scoped keys are rejected there.
- **One key per region.** US and EU are separate deployments with separate users and keys — repeat the mint on each region you support. `user:read` also powers the region routing: the MCP server probes both regions with your token via `/api/users/@me/`, so a key missing it misroutes (defaults to US) on top of hiding the tools.

## Step 2: connect your MCP client

Add the PostHog MCP server with the key as a bearer token.
The URL is the same for both regions — the server probes US and EU with your token and routes to the region that recognizes it, so the token itself selects the region.
For Claude Code, one entry per region you support:

```json
{
  "mcpServers": {
    "posthog-us": {
      "type": "http",
      "url": "https://mcp.posthog.com/mcp",
      "headers": { "Authorization": "Bearer ${POSTHOG_SUPPORT_PAT_US}" }
    },
    "posthog-eu": {
      "type": "http",
      "url": "https://mcp.posthog.com/mcp",
      "headers": { "Authorization": "Bearer ${POSTHOG_SUPPORT_PAT_EU}" }
    }
  }
}
```

Keep the tokens in env vars or a secret manager rather than inline.
Both connections can coexist with your everyday PostHog MCP connection — tools are namespaced per server, so the staff tools stay out of your daily driver's tool list.

Do **not** sign in via the OAuth browser flow — OAuth tokens structurally cannot carry the hidden scope, so the support tools will never appear on an OAuth connection.
The bearer-header PAT is the only path.

A note on scoping: a minimal support key (`batch_import_support:read` + `user:read`) surfaces only the two staff tools plus scope-free utilities — every other tool needs scopes the key lacks.
That's the recommended least-privilege setup for a dedicated support connection.
If you want one key that also carries the full normal toolset, mint it with `["*", "batch_import_support:read"]` — the `*` unlocks everything else while the explicit hidden scope satisfies the staff gate — at the cost of a much more powerful credential sitting in your config.

## Step 3: verify

Ask your agent to list managed migration support tools, or search for `managed-migrations-support`.
With the key above you should see both tools; a quick smoke test is listing imports for a known team id.

If the tools don't appear, check in order:

1. Key has `batch_import_support:read` **explicitly** (not via `*`)
2. Key has `user:read` (or `*` alongside the explicit support scope)
3. Your user is staff on that region
4. The key is unscoped and you're connected to the right region
5. Fresh key: the MCP server caches a token's scopes, so a key whose scopes were edited after first use can serve stale results — mint a new one

## How it's enforced (for the curious)

The MCP-side filtering is presentation, not security: it exists so staff-only tools never pollute customer tool lists.
The security boundary is the Django endpoint (`/api/managed_migrations_support/`), which requires an authenticated staff user plus the explicit scope, rejects wildcard keys, and audit-logs every read.
See `products/managed_migrations/backend/api/support_batch_imports.py` and `services/mcp/src/lib/staff-only-tools.ts`.

For testing changes to any of this locally, use the [testing-mcp-tools-locally](../skills/testing-mcp-tools-locally/SKILL.md) skill.
