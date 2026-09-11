# oauth-proxy

Cloudflare Worker behind `oauth.posthog.com`.
It gives OAuth clients a single set of endpoints in front of both PostHog Cloud regions (`us.posthog.com` and `eu.posthog.com`) and routes each request to the region the user belongs to.

Without it, every integration would have to ship two sets of OAuth URLs and ask users which region they are on before the flow starts.
The PostHog MCP server and PostHog Desktop both point at this worker, and new integrations should too.

The worker is stateless apart from a KV namespace (`AUTH_KV`) that remembers which region a flow picked and the client registrations it created in each region.
Access tokens are issued and validated only by the regional PostHog instances.
The one exception is the OpenID Connect ID token: the worker verifies the regional one and signs it again under its own issuer, because the claims a relying party checks (`iss` and `aud`) have to name this proxy and the client's own `client_id`. See [ID tokens](#id-tokens).

## Routes

| Method | Path                                      | Description                                                                        |
| ------ | ----------------------------------------- | ---------------------------------------------------------------------------------- |
| `GET`  | `/.well-known/oauth-authorization-server` | RFC 8414 metadata, fetched from US and rewritten to point at the proxy (10m cache) |
| `GET`  | `/.well-known/openid-configuration`       | OIDC discovery, fetched from US and rewritten the same way (10m cache)             |
| `GET`  | `/.well-known/jwks.json`                  | This proxy's signing keys, plus the regional keys                                  |
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
   The worker stores the region choice in KV under the `client_id`, swaps in the regional `client_id`, replaces `redirect_uri` with the proxy callback, and redirects to the region.
   For clients with a stored `redirect_uris` list, it also generates a nonce, stores the client's original `redirect_uri` and `state` under it, and sends the regional server that nonce as `state` instead of the client's own.
3. **Callback.**
   The regional server sends the user to `/oauth/callback` with the nonce from step 2 as `state`.
   The worker looks up and deletes the matching record, then forwards every query param to the client's original `redirect_uri`, restoring the client's own `state`.
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

## ID tokens

A regional server signs an ID token with its own issuer (`https://us.posthog.com` or `https://eu.posthog.com`) and with the regional `client_id` as the audience.
A client that discovered this proxy knows neither value: it reads `https://oauth.posthog.com` as the issuer, and it holds the proxy `client_id`, which is the US one.
Both claims fail the checks a conformant OpenID relying party runs, and the audience is wrong for every EU user.

So `/oauth/token` verifies the regional ID token against that region's published keys, then signs the same claims again with this worker's key, under the proxy issuer and the client's own `client_id`.
`iat` and `exp` are copied rather than recomputed, so re-issuing can neither extend a token nor invent an authentication event.
Responses with no `id_token` pass through untouched, which covers the ID-JAG exchange and every client that did not request the `openid` scope.

`/.well-known/jwks.json` publishes this worker's keys next to the regional ones.
The regional keys stay because the regional servers also sign the ID-JAG access tokens (`at+jwt`) that clients receive through this proxy.
Key ids differ, so a verifier selects the right key on its own.

### Signing keys

| Secret                        | Role                                                   |
| ----------------------------- | ------------------------------------------------------ |
| `OIDC_SIGNING_KEY`            | PKCS#8 PEM. Signs every ID token the proxy issues.     |
| `OIDC_SIGNING_KEY_INACTIVE_1` | PKCS#8 PEM. Published in JWKS, never used for signing. |

Generate a key with:

```sh
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -outform PEM -out oidc-signing-key.pem
```

Paste the file's contents into the Cloudflare dashboard as a secret on the `auth-proxy` worker, or run `wrangler secret put OIDC_SIGNING_KEY`.
The worker also accepts a PEM whose newlines are written as `\n`, matching how the Django `OIDC_RSA_PRIVATE_KEY` setting is stored.
Delete the local file once the secret is set.

To rotate, move the current key to `OIDC_SIGNING_KEY_INACTIVE_1`, set the new one as `OIDC_SIGNING_KEY`, and drop the old one after the longest ID token lifetime has passed.

Without `OIDC_SIGNING_KEY` the worker serves the regional ID token unchanged and logs `id_token: passthrough_no_signing_key`, so deploying the code before the secret exists degrades to today's behavior instead of failing token exchanges.

## KV keys

| Key                         | TTL    | Value                                                                 |
| --------------------------- | ------ | --------------------------------------------------------------------- |
| `client:<proxy_id>`         | none   | US and EU `client_id`s, secrets, and registered `redirect_uris`       |
| `region:<sha256>`           | 1 hour | `us` or `eu`, stored under `client_id`                                |
| `callback:<sha256>`         | 1 hour | The client's original `redirect_uri`, stored under `client_id`        |
| `pending_callback:<sha256>` | 1 hour | The client's original `redirect_uri` and `state`, under a proxy nonce |

Key material is SHA-256 hashed because `state` and the nonce are opaque and can exceed Cloudflare's 512 byte key limit.
`pending_callback:` records are deleted once `/oauth/callback` reads them, so a nonce is single-use.
KV is eventually consistent across Cloudflare's edge locations, so this single-use guarantee is best effort; the authorization code itself is still single-use at the regional server.

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
Secrets are not in that file: set them in the Cloudflare dashboard or with `wrangler secret put`.
