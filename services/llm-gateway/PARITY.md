# Choosing an AI gateway

✅ **Default to [`PostHog/ai-gateway`](https://github.com/PostHog/ai-gateway)** for new callers.

⚠️ **Keep `services/llm-gateway`** when the Go gateway does not support the caller's contract.

## ✅ Ready on the Go gateway

- OpenAI Chat Completions and Responses
- Anthropic Messages and token counting
- Streaming and non-streaming requests
- `phs_` and `pha_` credentials
- Distinct ID, trace, and custom property attribution
- OpenAI, Anthropic, Azure OpenAI, Bedrock, and selected Modal models

Existing Django callers should use `build_openai_client`, `build_async_openai_client`, or `build_async_anthropic_client` from [`posthog/llm/gateway_client.py`](../../posthog/llm/gateway_client.py). These builders keep the Python fallback during rollout.

## ⚠️ Check before migrating

| Area                   | Blocker                                                                                                           | Action                                                                                            |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Product policy         | The Go gateway does not enforce Python `ProductConfig` rules or trusted `$ai_product` policy.                     | Keep callers that depend on product model allowlists, auth rules, or unbilled products on Python. |
| Billing and limits     | Go uses prepaid wallet admission. Python has product and user limits, plan checks, quotas, and unbilled products. | Confirm the call should debit the Go wallet.                                                      |
| Authentication         | Python accepts `phx_` and `pha_`. Go accepts `phs_` and `pha_`.                                                   | Provision a supported credential and verify its scope, team, and model allowlist.                 |
| Providers              | Go does not yet support OpenRouter, Fireworks, Cloudflare, or Baseten.                                            | Keep models on Python until their provider is in the Go catalog.                                  |
| API surfaces           | Go has no audio transcription endpoint. The gateways also expose different usage APIs.                            | Check the exact path and response contract.                                                       |
| Models and translation | Go owns a stricter model catalog and does not translate OpenAI models to Anthropic Messages.                      | Confirm the model appears in `GET /v1/models` and supports the chosen API shape.                  |
| Fallback behavior      | Python has opt-in Bedrock fallback. Go routes by host health unless `X-PostHog-Provider` pins a host.             | Confirm the required provider and fallback behavior.                                              |
| Request metadata       | Go reads `X-PostHog-Properties`, not Python's per-key property or feature flag headers.                           | Convert metadata to the JSON properties header.                                                   |

## Migration checklist

1. Start with the Go gateway and a shared builder.
2. Check the caller against every applicable blocker above.
3. Keep the Python fallback when blocked. Record the specific gap in the change.
4. Test the selected gateway, including streaming, provider errors, attribution, and billing when relevant.

## References

- Python gateway: [`services/llm-gateway`](./README.md)
- Go gateway: [`PostHog/ai-gateway`](https://github.com/PostHog/ai-gateway), especially `docs/product.md`

Update this file when a gap closes or a new incompatibility is found.
