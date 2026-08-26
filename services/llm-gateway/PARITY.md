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
| Stock SDK proxy               | The caller needs OpenAI Chat Completions or Responses, Anthropic Messages or token counting, streaming, idempotency, or the model catalog.                                        |
| Gateway-managed routing       | The caller accepts operator-managed provider plans and health-aware selection across OpenAI, Anthropic, Azure OpenAI, Bedrock, or configured Modal, Fireworks, and Baseten hosts. |

Existing Django callers should use `build_openai_client`, `build_async_openai_client`, or `build_async_anthropic_client` from [`posthog/llm/gateway_client.py`](../../posthog/llm/gateway_client.py). The OpenAI builders forward caller-selected distinct IDs, traces, sessions, and metadata while keeping a temporary Python fallback during rollout.

### ⛔ Stay on the Python gateway for now

| Use case                                                                                          | Blocking contract                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PostHog Desktop, PostHog Code, cloud agents, onboarding, Wizard, and similar first-party products | Trusted product identity, OAuth application allowlists, OAuth user attribution, server-minted credential requirements, per-product model policy, free-tier model allowlists, and product billing or unbilled policy are not available together in Go. Desktop also requires a request-selected project validated against OAuth scope, live organization membership, and project-level access control, followed by a Django policy decision for Startup programs and prepaid credits. An `ai_product` event property is not an authorization or billing boundary. |
| Product or user budget enforcement                                                                | Python supports product and user cost limits, plan checks, quota buckets, and requests that debit no wallet. Go currently admits against the credential owner's team wallet and does not branch settlement on credential billing mode.                                                                                                                                                                                                                                                                                                                           |
| Agent runs a customer can start on demand                                                         | Python bounds one run's total spend against the task its credential was minted for, and picks the budget from the token's provenance rather than from the product the caller declares. Go has neither, so both the per-run ceiling and the pipeline-versus-user-started split would be lost on migration.                                                                                                                                                                                                                                                        |
| OpenRouter or Cloudflare Workers AI                                                               | These provider paths are not available in Go.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| OpenAI audio transcription                                                                        | Go has no transcription endpoint.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| OpenAI models through Anthropic Messages                                                          | Go does not provide this reverse translation.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| Python product usage status                                                                       | The Python product usage and quota API is different from Go request usage and wallet APIs.                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |

For PostHog Desktop, the Python gateway maps Django credential rejections to generic access denials. Transport, server, and malformed-response failures remain retryable service errors.

### 🔎 Verify before switching

These are compatibility checks, not automatic blockers:

- **Model:** it appears in `GET /v1/models` and supports the requested API shape and capabilities.
- **Credential:** Go accepts the credential type and projects the correct team, scope, and revocation state.
- **Billing:** identify which team owns the Go credential and should pay, then confirm its wallet is funded for the expected usage. Internal workloads can debit a PostHog-owned team wallet so spend stays attributable without charging a customer.
- **Attribution:** `X-PostHog-Distinct-Id`, `X-PostHog-Trace-Id`, and `X-PostHog-Properties` provide enough event context. Go does not derive the event distinct ID from OpenAI `user`, Anthropic `metadata.user_id`, or the OAuth user. Caller-supplied properties are not trusted policy.
- **Session attribution:** `X-PostHog-Session-Id` provides the required gateway-owned `$ai_session_id`.
- **Provider deployment:** Fireworks and Baseten host support exists in Go, but the target environment must declare the required host and credentials. Baseten also requires approved-subprocessor status before deployment.
- **Provider behavior:** operator routing policy, health-aware provider ordering, or strict `X-PostHog-Provider` pinning matches the caller's fallback requirements.
- **Wire behavior:** request fields, streaming chunks, errors, timeouts, and retries match what the caller handles.
- **Metadata:** Python per-key property and feature flag headers are converted to the Go JSON properties header.

## Parity map

| Contract                     | Go gateway today                                                                                                                                                   | Python-only behavior that can block migration                                                                                                                                                                                                                                                                                |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Authentication               | `phs_` project secrets and `pha_` OAuth credentials with the literal `llm_gateway:read` scope; credential resolves a fixed team and revocation state.              | `phx_` personal keys, wildcard OAuth scope handling, product-specific API key or OAuth application rules, and Desktop's request-selected project validated against OAuth scope and live organization membership.                                                                                                             |
| Trusted first-party identity | No trusted product identity or product-scoped authorization boundary.                                                                                              | Product route selects allowlisted OAuth apps, server credential requirements, model policy, and the project-scoped PostHog Desktop policy on `posthog_code`. Django applies the access override before Startup-program and prepaid-credit restrictions; server-minted `internal_run:read` credentials bypass the human gate. |
| Attribution                  | Distinct ID comes from `X-PostHog-Distinct-Id` or falls back to team ID. Supports trace ID, custom JSON properties, team project token, provider, usage, and cost. | OAuth user identity, ACL-resolved OAuth team attribution, staff-owned personal-key customer-team overrides, body-derived end-user identity, gateway-owned `$ai_product` and `$ai_billable`, per-key properties, and feature flag headers.                                                                                    |
| Billing and limits           | Wallet reservation and settlement, idempotency, balance read, request usage read, and front-line rate limiting.                                                    | Product and user cost windows, per-sandbox-run ceilings keyed on the credential's task binding, budget keys derived from token scopes rather than the declared product, plans, quota buckets, product-specific free-tier model allowlists, unbilled products, and product usage status.                                      |
| OpenAI APIs                  | Chat Completions, Responses, bare Responses alias, and normalized router chat.                                                                                     | Audio transcription and broader LiteLLM translation.                                                                                                                                                                                                                                                                         |
| Anthropic APIs               | Messages and token counting, including Bedrock-hosted models.                                                                                                      | OpenAI models exposed through the Anthropic shape and Python-specific Bedrock opt-in behavior.                                                                                                                                                                                                                               |
| Providers                    | OpenAI, Anthropic, Azure OpenAI, Bedrock, and configured Modal, Fireworks, and Baseten hosts.                                                                      | OpenRouter and Cloudflare Workers AI.                                                                                                                                                                                                                                                                                        |
| Models                       | Gateway-owned catalog, canonical IDs and aliases, capability checks, router categories, and OpenRouter-shaped pricing.                                             | Broader LiteLLM model acceptance, Python product allowlists, and product-scoped model pricing.                                                                                                                                                                                                                               |
| Routing and failure behavior | Operator-managed provider plans, health-aware ordering, circuit breakers, hosted-provider failover, and strict provider pinning.                                   | Caller opt-in Bedrock fallback and provider-specific Python routing.                                                                                                                                                                                                                                                         |
| Event metadata               | One `X-PostHog-Properties` JSON object plus dedicated distinct ID, trace ID, and provider headers.                                                                 | `X-POSTHOG-PROPERTY-*` and `X-POSTHOG-FLAG-*` headers.                                                                                                                                                                                                                                                                       |
| Session attribution          | `X-PostHog-Session-Id` is recorded as the gateway-owned `$ai_session_id`.                                                                                          | The per-key property header can also emit `$ai_session_id`.                                                                                                                                                                                                                                                                  |

## Migration checklist

Run `/migrating-llm-gateway-callers` to inventory and convert a caller.

1. Describe the caller and identify which identity controls its access and spend.
2. Check every relevant contract above against the real request and response.
3. Start with a shared Go-capable builder where one exists.
4. Test success, streaming if used, provider errors, attribution, and billing.
5. Keep the Python fallback only for staged rollout or a named blocker. Record the rollout plan or blocker in the PR.

## Refreshing this document

Run `/auditing-llm-gateway-parity` after either gateway changes auth, attribution, billing, endpoints, providers, models, routing, or event metadata. The skill audits implementation sources in both repositories and updates this file without migrating callers.

Last verified on 2026-08-24 against:

- `PostHog/posthog` working tree compared with master at `e579a630700a93bc6a325758015c5e1227f05267`
- `PostHog/ai-gateway` main at `9a9826ea448b3f5fcddeb8bc09ef187963a93902`

## References

- Python gateway: [`services/llm-gateway`](./README.md)
- Shared clients: [`posthog/llm/gateway_client.py`](../../posthog/llm/gateway_client.py)
- Go gateway: [`PostHog/ai-gateway`](https://github.com/PostHog/ai-gateway), especially `docs/product.md`
