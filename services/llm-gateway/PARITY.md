# AI gateway parity

Use [`PostHog/ai-gateway`](https://github.com/PostHog/ai-gateway) for new LLM gateway callers when it supports the caller's contract. `services/llm-gateway` remains available for callers that depend on a gap below.

This is a migration checklist, not a promise that similarly named endpoints behave identically. Check the current implementations before moving a caller:

- Python gateway: [`services/llm-gateway`](./README.md)
- Go gateway: [`PostHog/ai-gateway`](https://github.com/PostHog/ai-gateway), especially `docs/product.md`
- Shared PostHog client builders: [`posthog/llm/gateway_client.py`](../../posthog/llm/gateway_client.py)

## Supported migration baseline

The Go gateway supports the main unprefixed OpenAI Chat Completions, OpenAI Responses, Anthropic Messages, Anthropic token-counting, and model-list surfaces. It supports streaming and non-streaming calls, `phs_` and `pha_` credentials, end-user attribution with `X-PostHog-Distinct-Id`, trace attribution with `X-PostHog-Trace-Id`, and event properties with the `X-PostHog-Properties` JSON header.

Use `build_openai_client`, `build_async_openai_client`, or `build_async_anthropic_client` from `posthog/llm/gateway_client.py` when an existing Django caller can use this baseline. These builders select the Go gateway when configured and retain the Python gateway fallback during rollout.

## Known parity gaps

| Area                              | Python gateway                                                                                                                    | Go gateway                                                                                                                                                                | Migration check                                                                                                                                        |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Product policy and attribution    | Product-prefixed routes select model allowlists, authentication rules, billing, quotas, and `$ai_product`.                        | Routes are not product-prefixed. Callers can attach `ai_product` as an event property, but product policy and budgets are not equivalent yet.                             | Do not migrate a caller that relies on Python `ProductConfig` enforcement or an unbilled product until the Go gateway has the matching trusted policy. |
| Billing and limits                | Supports per-product and per-user cost limits, plan and quota checks, billable credit buckets, and unbilled products.             | Uses prepaid wallet admission and a front-line rate limit. The credential billing mode is carried but does not yet change settlement.                                     | Confirm the caller should debit the Go gateway wallet and does not require Python quota or free-tier behavior.                                         |
| Authentication                    | Accepts `phx_` personal API keys and `pha_` OAuth tokens, with product-specific rules.                                            | Accepts `phs_` project secret keys and `pha_` OAuth tokens from the gateway credential cache.                                                                             | Provision a supported credential and confirm its scope, revocation, team, and model allowlist projections.                                             |
| Provider coverage                 | Supports direct OpenAI and Anthropic plus Bedrock, OpenRouter, Fireworks, Cloudflare Workers AI, Modal, and Baseten routes.       | Supports OpenAI, Anthropic, Azure OpenAI, Bedrock, and selected Modal-hosted models.                                                                                      | Keep callers that require OpenRouter, Fireworks, Cloudflare, or Baseten on Python until that provider and model are in the Go catalog.                 |
| API surfaces                      | Adds product-prefixed variants and OpenAI audio transcription. Its usage endpoint reports product cost and quota status.          | Adds normalized router, request-usage, wallet, and idempotency surfaces, but has no audio transcription endpoint.                                                         | Check the exact path and response contract. The two usage APIs are different products, not aliases.                                                    |
| Model identifiers and translation | LiteLLM accepts a broad set of model IDs and can route Anthropic models through the OpenAI-compatible surface.                    | The catalog owns canonical models and aliases. The normalized router translates selected Anthropic models to OpenAI shapes, but the reverse translation is not available. | Confirm the requested model is in `GET /v1/models` and works on the chosen API shape.                                                                  |
| Provider selection and fallback   | Supports explicit Bedrock selection and opt-in Bedrock fallback headers, plus gateway-specific routing for several hosted models. | Chooses between configured hosts using health and priority, with strict `X-PostHog-Provider` pinning when needed.                                                         | Verify whether the caller requires a fixed provider, automatic failover, or the Python fallback semantics.                                             |
| Request metadata                  | Accepts per-key property and feature-flag headers.                                                                                | Accepts one `X-PostHog-Properties` JSON object and dedicated distinct-id, trace-id, and provider headers.                                                                 | Convert metadata to the JSON header. Do not assume Python's per-key or feature-flag headers are read.                                                  |

## Adding a caller

1. Start with the Go gateway and a shared builder.
2. Check every applicable row above against the caller's actual request, credential, model, provider, attribution, and billing behavior.
3. If a gap blocks the caller, keep the Python fallback and record the specific gap in the change. Avoid adding a second implementation to both gateways unless both services must own the behavior during migration.
4. Test the request against the selected gateway. Include streaming, provider errors, attribution properties, and billing behavior when the caller depends on them.

Update this file when a gap closes or a new incompatibility is found. Keep detailed Go gateway behavior in its own `docs/product.md`; this file should only describe migration-relevant differences.
