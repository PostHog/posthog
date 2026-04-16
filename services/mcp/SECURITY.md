# MCP server security

The PostHog MCP server is a Cloudflare Worker that proxies authenticated
requests from Model Context Protocol clients to the PostHog API. This note
documents the trust model and the guardrails that keep it safe to run in
production.

## Trust model

1. **Inbound transport is HTTPS only.** Cloudflare terminates TLS in front of
   the Worker; the Worker itself never speaks HTTP.
2. **Every request must present an OAuth bearer token.** The Worker refuses
   unauthenticated requests at `src/index.ts` with a `401` and an RFC 9728
   `WWW-Authenticate` header. Token format is strictly validated
   (`phx_` / `pha_` prefix + URL-safe base64 charset, 8–256 chars) to prevent
   header smuggling through the outbound `Authorization: Bearer …` header.
3. **Authorization is delegated to PostHog.** The Worker never issues, signs,
   or introspects tokens itself — it only forwards the bearer token and lets
   the PostHog API enforce scopes. The only authorization decisions made in
   the Worker are (a) filtering tools by advertised OAuth scopes before
   registering them with the MCP client (`src/tools/index.ts`) and (b)
   caching the introspection result in a durable object keyed by PBKDF2 hash
   of the token.
4. **No shell, no filesystem, no arbitrary outbound fetch.** Cloudflare
   Workers do not expose child processes, a filesystem, or the Node.js `net`
   stack. The Worker's egress is limited to two destinations: the regional
   PostHog API (`https://us.posthog.com` / `https://eu.posthog.com`, or
   `POSTHOG_API_BASE_URL` for self-hosted deployments), and the Inkeep docs
   completion endpoint (`https://api.inkeep.com/v1/chat/completions`, gated
   on the `INKEEP_API_KEY` secret). Every outbound request goes through
   `src/api/client.ts` or `src/api/fetcher.ts`, both of which only
   concatenate to a region-derived base URL.

## Validated inputs at the trust boundary

Values that eventually land in URL paths, outbound headers, or OAuth
discovery metadata are validated against explicit allowlists in
`src/lib/validation.ts`:

- **`Authorization: Bearer …` token** — must start with `phx_` or `pha_`,
  followed by 8–256 URL-safe base64 characters (`A-Z a-z 0-9 _ -`).
- **`x-posthog-project-id` / `?project_id`** — must be the literal `@current`
  or a 1–20 digit integer.
- **`x-posthog-organization-id` / `?organization_id`** — must be the literal
  `@current` or a UUID (any case).
- **`?region`** — must be exactly `us` or `eu` (case-insensitive).
- **`X-Forwarded-Host`** — must be syntactically a hostname AND the request
  itself must be coming in on a known PostHog proxy hostname or a local dev
  hostname.

Anything that fails validation is rejected with `400` or `401` at
`src/index.ts` before any durable-object state is touched, the MCP server is
constructed, or the upstream PostHog API is called.

## Defense in depth

- `getProjectBaseUrl` (hand-written API client) URL-encodes the projectId
  even though the entry-level validator already rejects malformed values.
- `switch-organization` re-validates its model-supplied `orgId` before
  writing it to the cache.
- `init()` in `src/mcp.ts` re-validates `organizationId` and `projectId`
  before seeding the durable object cache.
- All error-message paths (`client.ts`, `fetcher.ts`, `logging.ts`,
  `inkeepApi.ts`) pass upstream response bodies through `redactSecrets()` so
  a misbehaving upstream can't echo the bearer token into observability
  logs.
- Request logging redacts `authorization`, `cookie`, and `x-api-key` headers
  at ingress; upstream `Authorization` tokens are stripped from error
  messages at egress.
- Outbound requests are rate-limited (10 rps) via `api/rate-limiter.ts`
  independent of whatever the client is doing.

## Deployment hardening checklist

- [ ] Deploy only as a Cloudflare Worker. Do not port the handler to a
      STDIO / shell MCP runtime without re-auditing — this code assumes a
      sandboxed runtime with no child processes and no filesystem.
- [ ] Keep `POSTHOG_API_BASE_URL` **unset** for PostHog Cloud. Only set it
      for self-hosted deployments, and only to an HTTPS URL you control.
- [ ] Rotate `INKEEP_API_KEY` and `POSTHOG_UI_APPS_TOKEN` on a schedule;
      both are Cloudflare Worker secrets (never env vars).
- [ ] Ensure inbound traffic only reaches the Worker via Cloudflare. Direct
      worker.dev hostnames should be disabled for production so that the
      `shouldHonorForwardedHost` allowlist is the only path by which
      `X-Forwarded-Host` can influence OAuth metadata.
- [ ] Confirm the Worker runs under the minimum scopes required. OAuth
      scopes advertised in `OAUTH_SCOPES_SUPPORTED` are the maximum set of
      scopes any MCP client can request; narrow this list if a hosting
      environment should not expose the full catalog.
- [ ] Pin upstream dependencies via `pnpm-lock.yaml`; audit new
      dependencies before upgrading (the server imports `posthog-node`,
      `posthog-js-lite`, `@modelcontextprotocol/sdk`, `zod`, `uuid`,
      `mcpcat`, `@toon-format/toon`, and `agents` — any of these landing a
      malicious version would bypass everything documented above).
- [ ] Keep Cloudflare Worker observability enabled (`wrangler.jsonc`) so
      that anomalous tool-call patterns (`authError` codes, invalid region,
      invalid ID formats) surface in logs.
- [ ] Run `pnpm test` on every change — the security regression suite
      (`tests/unit/validation.test.ts`,
      `tests/unit/setActive.security.test.ts`) asserts that each hostile
      payload in the table above is still rejected.

## Reporting

Report suspected vulnerabilities to `security@posthog.com`. Do not open
public issues for security findings.
