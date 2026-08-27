# Choosing an AI gateway

✅ **Default to [`PostHog/ai-gateway`](https://github.com/PostHog/ai-gateway)** for new callers and features.

⚠️ **Use `services/llm-gateway` temporarily** only when an active caller is blocked by a gap below.

## Migration policy

`services/llm-gateway` is under an unofficial code freeze. Everyone should move to the Go gateway unless they can name a contract it does not support.

A PR that changes the Python gateway must:

1. Name the active caller and its use case.
2. Name the exact Go gateway parity gap.
3. Explain why the change cannot wait for or land in the Go gateway.
4. Limit the Python change to the blocked caller's needs.
5. Update this document when it discovers or closes a gap.

Bug, security, and reliability fixes for blocked callers are valid reasons. Convenience, an existing Python client, or an unfamiliar Go API are not parity gaps.

When a gap closes, new work uses the Go gateway and affected callers should migrate. Do not add the same feature to both gateways by default.

## Choose by use case

### ✅ Use the Go gateway

| Use case                      | Why it fits                                                                                                                                                                       |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Customer LLM traffic          | The caller uses a project secret or OAuth credential, the team wallet should pay, and standard OpenAI or Anthropic APIs are enough.                                               |
| Server-to-server PostHog call | A `phs_` credential, team wallet billing, and informational event properties provide enough policy and attribution. Internal spend can use a PostHog-owned team wallet.           |
| Capped delegated run          | A standard credential can mint a short-lived `phe_` token with pinned attribution and a per-token spend cap.                                                                      |
| Stock SDK proxy               | The caller needs OpenAI Chat Completions or Responses, Anthropic Messages or token counting, streaming, idempotency, or the model catalog.                                        |
| Gateway-managed routing       | The caller accepts operator-managed provider plans and health-aware selection across OpenAI, Anthropic, Azure OpenAI, Bedrock, or configured Modal, Fireworks, and Baseten hosts. |

Existing Django callers should use `build_openai_client`, `build_async_openai_client`, or `build_async_anthropic_client` from [`posthog/llm/gateway_client.py`](../../posthog/llm/gateway_client.py). The builders forward product attribution and caller-selected metadata while keeping a temporary Python fallback during rollout.

### ⛔ Stay on the Python gateway for now

| Use case                                                                                          | Blocking contract                                                                                                                                                                                                                                                                                                                                                                                            |
| ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| PostHog Desktop, PostHog Code, cloud agents, onboarding, Wizard, and similar first-party products | Go can pin product and user attribution in a scoped token, but it does not apply Django's OAuth application allowlists, project access checks, plans, or billing policy. Desktop also requires a request-selected project validated against OAuth scope, live organization membership, and project-level access control. An asserted product remains caller-controlled and is not an authorization boundary. |
| Django plan or quota enforcement                                                                  | Go supports rolling attribution budgets, a hard team cap, and per-token caps. Python still owns plan checks, quota buckets, free-model policy, and requests that debit no wallet.                                                                                                                                                                                                                            |
| Agent runs a customer can start on demand                                                         | Go can cap one run with a scoped token, but the Django integration only mints tokens for server-authorized internal products. User-started runs still need Python's provenance-based policy.                                                                                                                                                                                                                 |
| OpenRouter or Cloudflare Workers AI                                                               | These provider paths are not available in Go.                                                                                                                                                                                                                                                                                                                                                                |
| OpenAI audio transcription                                                                        | Go has no transcription endpoint.                                                                                                                                                                                                                                                                                                                                                                            |
| OpenAI models through Anthropic Messages                                                          | Go does not provide this reverse translation.                                                                                                                                                                                                                                                                                                                                                                |
| Python product usage status                                                                       | The Python product usage and quota API is different from Go request usage and wallet APIs.                                                                                                                                                                                                                                                                                                                   |

For PostHog Desktop, the Python gateway maps Django credential rejections to generic access denials. Transport, server, and malformed-response failures remain retryable service errors.

### 🔎 Verify before switching

These are compatibility checks, not automatic blockers:

- **Model:** it appears in `GET /v1/models` and supports the requested API shape and capabilities.
- **Credential:** Go accepts `phs_`, `pha_`, and gateway-minted `phe_` credentials. Confirm the resolved team, scope, revocation state, attribution, and cap.
- **Billing:** identify which team owns the Go credential and should pay, then confirm its wallet is funded for the expected usage. Internal workloads can debit a PostHog-owned team wallet so spend stays attributable without charging a customer.
- **Attribution:** `X-PostHog-Product`, `X-PostHog-Distinct-Id`, `X-PostHog-Trace-Id`, and `X-PostHog-Properties` provide enough event context. Go does not derive the event distinct ID from OpenAI `user`, Anthropic `metadata.user_id`, or the OAuth user. Caller-supplied attribution is not trusted policy.
- **Session attribution:** `X-PostHog-Session-Id` provides the required gateway-owned `$ai_session_id`.
- **Provider deployment:** Fireworks and Baseten host support exists in Go, but the target environment must declare the required host and credentials. Baseten also requires approved-subprocessor status before deployment.
- **Provider behavior:** operator routing policy, health-aware provider ordering, or strict `X-PostHog-Provider` pinning matches the caller's fallback requirements.
- **Wire behavior:** request fields, streaming chunks, errors, timeouts, and retries match what the caller handles.
- **Metadata:** Python per-key property and feature flag headers are converted to the Go JSON properties header.

## Parity map

| Contract                     | Go gateway today                                                                                                                                                                  | Python-only behavior that can block migration                                                                                                                                                                           |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Authentication               | `phs_` project secrets and `pha_` OAuth credentials require `llm_gateway:read`. Standard credentials can mint capped and revocable `phe_` tokens.                                 | `phx_` personal keys, wildcard OAuth scope handling, product-specific API key or OAuth application rules, and Desktop's request-selected project validated against OAuth scope and live organization membership.        |
| Trusted first-party identity | Scoped tokens pin product, user, and obo attribution at mint. Standard credential headers remain caller-controlled and do not authorize a product.                                | Product routes select allowlisted OAuth apps, server credential requirements, model policy, and Django product policy. Django also decides which callers may receive a product-scoped credential.                       |
| Attribution                  | Distinct ID comes from `X-PostHog-Distinct-Id` or falls back to a namespaced team identity. Product, user, and obo attribution land on events and ledger entries with provenance. | OAuth user identity, ACL-resolved OAuth team attribution, staff-owned personal-key customer-team overrides, body-derived end-user identity, gateway-owned `$ai_billable`, per-key properties, and feature flag headers. |
| Billing and limits           | Wallet reservation and settlement, soft attribution budgets, a hard team cap, per-token caps, idempotency, balance and usage reads, and front-line rate limits.                   | Plans, quota buckets, product-specific free-model policy, unbilled products, product usage status, and Django provenance rules that decide which cap applies.                                                           |
| OpenAI APIs                  | Chat Completions, Responses, bare Responses alias, and normalized router chat.                                                                                                    | Audio transcription and broader LiteLLM translation.                                                                                                                                                                    |
| Anthropic APIs               | Messages and token counting, including Bedrock-hosted models.                                                                                                                     | OpenAI models exposed through the Anthropic shape and Python-specific Bedrock opt-in behavior.                                                                                                                          |
| Providers                    | OpenAI, Anthropic, Azure OpenAI, Bedrock, and configured Modal, Fireworks, and Baseten hosts.                                                                                     | OpenRouter and Cloudflare Workers AI.                                                                                                                                                                                   |
| Models                       | Gateway-owned catalog, canonical IDs and aliases, capability checks, router categories, and OpenRouter-shaped pricing.                                                            | Broader LiteLLM model acceptance, Python product allowlists, and product-scoped model pricing.                                                                                                                          |
| Routing and failure behavior | Operator-managed provider plans, health-aware ordering, circuit breakers, hosted-provider failover, and strict provider pinning.                                                  | Caller opt-in Bedrock fallback and provider-specific Python routing.                                                                                                                                                    |
| Event metadata               | One `X-PostHog-Properties` JSON object plus dedicated product, user, obo, distinct ID, trace ID, and provider headers.                                                            | `X-POSTHOG-PROPERTY-*` and `X-POSTHOG-FLAG-*` headers.                                                                                                                                                                  |
| Session attribution          | `X-PostHog-Session-Id` is recorded as the gateway-owned `$ai_session_id`.                                                                                                         | The per-key property header can also emit `$ai_session_id`.                                                                                                                                                             |

## Migration checklist

Run `/migrating-llm-gateway-callers` to inventory and convert a caller.

1. Describe the caller and identify which identity controls its access and spend.
2. Check every relevant contract above against the real request and response.
3. Start with a shared Go-capable builder where one exists.
4. Test success, streaming if used, provider errors, attribution, and billing.
5. Keep the Python fallback only for staged rollout or a named blocker. Record the rollout plan or blocker in the PR.

## Refreshing this document

Run `/auditing-llm-gateway-parity` after either gateway changes auth, attribution, billing, endpoints, providers, models, routing, or event metadata. The skill audits implementation sources in both repositories and updates this file without migrating callers.

Last verified on 2026-08-25 against:

- `PostHog/posthog` working tree compared with master at `c22b95e0009c54388fd1b199d3248f48aba019e2`
- `PostHog/ai-gateway` main at `d7545e0979ff38d7df1ce73779253897c99c3c46`

## References

- Python gateway: [`services/llm-gateway`](./README.md)
- Shared clients: [`posthog/llm/gateway_client.py`](../../posthog/llm/gateway_client.py)
- Go gateway: [`PostHog/ai-gateway`](https://github.com/PostHog/ai-gateway), especially `docs/product.md`
