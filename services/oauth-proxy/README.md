# oauth-proxy

Cloudflare Worker behind `oauth.posthog.com`.
It gives OAuth clients a single set of endpoints in front of both PostHog Cloud regions (`us.posthog.com` and `eu.posthog.com`) and routes each request to the region the user belongs to.

Without it, every integration would have to ship two sets of OAuth URLs and ask users which region they are on before the flow starts.
The PostHog MCP server and PostHog Desktop both point at this worker, and new integrations should too.

The worker is stateless apart from a KV namespace (`AUTH_KV`) that remembers which region a flow picked and the client registrations it created in each region.
It never issues or validates tokens itself; the regional PostHog instances still do all of that.

## Routes

| Method | Path                                      | Description                                                                        |
| ------ | ----------------------------------------- | ---------------------------------------------------------------------------------- |
| `GET`  | `/.well-known/oauth-authorization-server` | RFC 8414 metadata, fetched from US and rewritten to point at the proxy (10m cache) |
| `GET`  | `/.well-known/jwks.json`                  | Proxied to US (keys are identical across regions)                                  |
| `POST` | `/oauth/register`, `/register`            | RFC 7591 dynamic registration, run against both regions at once                    |
| `GET`  | `/oauth/authorize`, `/authorize`          | Region picker page, then redirect to the regional authorize endpoint               |
| `GET`  | `/oauth/callback`                         | Receives the regional callback and forwards it to the client's `redirect_uri`      |
| `POST` | `/oauth/token`, `/token`                  | Token exchange, routed by region                                                   |
| `POST` | `/oauth/revoke`                           | Routed by `client_id`, falls back to trying both regions                           |
| `POST` | `/oauth/introspect`                       | US first, then EU (a 200 with `active: false` counts as a miss)                    |
| `GET`  | `/oauth/userinfo`                         | Tries both regions with the bearer token                                           |

Trailing slashes are optional; paths are normalized before matching.

## How a flow works

1. **Register.**
   `/oauth/register` forwards the registration to both regions in parallel and stores a `client:<id>` mapping in KV linking the US and EU `client_id` and `client_secret` pairs.
   The US `client_id` is handed back as the proxy `client_id`.
   The proxy's own `/oauth/callback/` is appended to the submitted `redirect_uris` so both regional servers accept it later.
2. **Authorize.**
   `/oauth/authorize` serves a static region picker.
   The picker re-requests the same URL with `_region=us|eu` appended.
   The worker stores that choice in KV under both the `state` and the `client_id`, swaps in the regional `client_id`, replaces `redirect_uri` with the proxy callback, and redirects to the region.
3. **Callback.**
   The regional server sends the user to `/oauth/callback`, which looks up the client's original `redirect_uri` by `state` and forwards every query param on to it.
   The client never sees a regional URL, so its token request comes back through the proxy.
4. **Token.**
   `/oauth/token` looks up the region by `client_id`.
   It rewrites `client_id`, `client_secret`, and `redirect_uri` back to the values the regional server issued the code for, then forwards the request.

Only clients that registered through the proxy get callback interception.
Clients registered directly against a region keep their own `redirect_uri` and fall through to that region's validation.

### Region resolution at the token endpoint

- A KV hit on `client_id` is the fast path.
- `authorization_code` grants with no stored region are rejected rather than replayed against both regions, because sending an auth code to the wrong server would leak it.
- `refresh_token` grants fall back to trying each region with the correctly rewritten `client_id`, then re-store the winner so later refreshes take the fast path.
- When both regions reject a request, the 4xx is forwarded in preference to the 5xx: a 4xx carries the OAuth error code the client acts on, while a 5xx only means one region was unhealthy.

## KV keys

| Key                 | TTL    | Value                                                           |
| ------------------- | ------ | --------------------------------------------------------------- |
| `client:<proxy_id>` | none   | US and EU `client_id`s, secrets, and registered `redirect_uris` |
| `region:<sha256>`   | 1 hour | `us` or `eu`, stored under both `state` and `client_id`         |
| `callback:<sha256>` | 1 hour | The client's original `redirect_uri`                            |

Key material is SHA-256 hashed because `state` is opaque and can exceed Cloudflare's 512 byte key limit.

## Development

```sh
pnpm --filter @posthog/auth-proxy install
pnpm --filter @posthog/auth-proxy dev        # wrangler dev
pnpm --filter @posthog/auth-proxy test       # vitest
pnpm --filter @posthog/auth-proxy typecheck  # tsgo --noEmit
pnpm --filter @posthog/auth-proxy cf-typegen # regenerate worker types
```

The worker always talks to production `us.posthog.com` and `eu.posthog.com`; there is no local-instance mode.
Local MCP development bypasses the proxy entirely, so you rarely need to run this service to work on a client.

Tests mock `fetch` and the KV namespace, so they need no Cloudflare credentials.
CI runs the typecheck and the test suite on any change under `services/oauth-proxy/` (see `.github/workflows/ci-oauth-proxy.yml`).

## Deploying

```sh
pnpm --filter @posthog/auth-proxy deploy
```

This needs Cloudflare credentials for the PostHog account.
The worker name, KV binding, and observability settings live in `wrangler.jsonc`.
