# LLM Gateway

A standalone microservice for proxying LLM requests to Anthropic, OpenAI, OpenRouter, and Fireworks AI APIs.

## Quick start

### Installation (for development)

```bash
cd services/llm-gateway
uv sync
uv run uvicorn llm_gateway.main:app --reload
```

### Making a request

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer phx_dev_local_test_api_key_1234567890abcdef" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4.1-mini",
    "messages": [{"role": "user", "content": "Hello"}],
    "user": "end-user-distinct-id"
  }'
```

## Authentication

The gateway supports two authentication methods:

| Method             | Token Prefix | Header                                                  |
| ------------------ | ------------ | ------------------------------------------------------- |
| Personal API Key   | `phx_`       | `Authorization: Bearer phx_...` or `x-api-key: phx_...` |
| OAuth Access Token | `pha_`       | `Authorization: Bearer pha_...`                         |

**Required Scope**: `llm_gateway:read`

### Local development key

When running via phrocs, a personal API key with the `llm_gateway:read` scope is **automatically provisioned** on startup.
The key is deterministic and survives database resets:

```text
phx_dev_local_test_api_key_1234567890abcdef
```

You can use this key directly to make requests to the gateway locally.
It is also available as `settings.DEV_API_KEY` in Django.

In local dev (`DEBUG=True`), the gateway client defaults to `http://localhost:3308` and this key,
so `get_llm_client(product=..., team_id=...)` works out of the box without setting any environment variables.

You can also provision the key manually:

```bash
python manage.py setup_local_api_key --add-scopes llm_gateway:read
```

`--add-scopes` merges into existing scopes without removing any.
`--scopes` replaces all scopes on the key.

## Database access

The gateway connects to the PostHog Postgres as a least-privilege role whose SELECT
grants are a per-table allowlist maintained in posthog-cloud-infra. The tables the
gateway reads are declared in `src/llm_gateway/db/required_tables.py`, and
`tests/test_required_tables.py` binds that declaration to the SQL in the package.
`/_readiness` verifies the connected role holds every declared grant on every probe,
so a revoked grant unreadies serving pods as well as new rollouts. To add a table
read, land the grant in every environment first, then declare the table.

## User attribution

When using an OAuth Access Token, the user who's token it is is the user used for analytics and rate limiting.

When calling the gateway on behalf of end-users with a Personal API Key, **always specify the end-user's identifier** if you want user based analytics / rate limiting:

### OpenAI SDK (Python)

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://gateway.us.posthog.com/v1",
    api_key="phx_your_api_key",
)

response = client.chat.completions.create(
    model="gpt-5-mini",
    messages=[{"role": "user", "content": "Hello"}],
    user="user_distinct_id_123",  # End-user attribution
)
```

### OpenAI SDK (TypeScript/JavaScript)

```typescript
import OpenAI from 'openai'

const client = new OpenAI({
  baseURL: 'https://gateway.us.posthog.com/v1',
  apiKey: 'phx_your_api_key',
})

const response = await client.chat.completions.create({
  model: 'gpt-5-mini',
  messages: [{ role: 'user', content: 'Hello' }],
  user: 'user_distinct_id_123', // End-user attribution
})
```

### Anthropic SDK (Python)

```python
import anthropic

client = anthropic.Anthropic(
    base_url="https://gateway.us.posthog.com/v1",
    api_key="phx_your_api_key",
)

response = client.messages.create(
    model="claude-opus-4-5",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello"}],
    metadata={"user_id": "user_distinct_id_123"},  # End-user attribution
)
```

## Feature flags

The gateway supports feature flags via the `X-POSTHOG-FLAG-*` headers. Feature flags are sent as `X-POSTHOG-FLAG-<FLAG_KEY>: <VALUE>` headers and appear on PostHog events as `$feature/<FLAG_KEY>: <VALUE>`.

## Custom event properties

The gateway supports capturing additional event properties to PostHog via the `X-POSTHOG-PROPERTY-*` headers. Event properties are sent as `X-POSTHOG-PROPERTY-<PROPERTY_KEY>: <VALUE>` headers and appear on PostHog events as `<PROPERTY_KEY>: <VALUE>`.

## API endpoints

### OpenAI-compatible

- `POST /v1/chat/completions` - Chat completions
- `POST /v1/responses` - OpenAI Responses API

### Anthropic-compatible

- `POST /v1/messages` - Anthropic Messages API (supports Bedrock via `X-PostHog-Provider`)
- `POST /v1/messages/count_tokens` - Anthropic token counting API (supports Bedrock via `X-PostHog-Provider`)

### Product-scoped endpoints

For product-specific rate limits and tracking:

- `POST /{product}/v1/chat/completions`
- `POST /{product}/v1/messages`

The product name is extracted from the first path segment and recorded as `ai_product` on `$ai_generation` events. See [Products](#products) for the full list and how to add one.

## Supported models

All OpenAI, Anthropic, OpenRouter, and Fireworks AI chat models are supported.
OpenRouter and Fireworks models use the OpenAI-compatible `/v1/chat/completions` endpoint with model prefixes (`openrouter/` and `fireworks_ai/`).
The `/v1/models` endpoint returns provider-specific model IDs from LiteLLM's model map.

## OpenAI organization

Set `LLM_GATEWAY_OPENAI_ORGANIZATION` to attribute all outbound OpenAI traffic
to a specific OpenAI organization (e.g. a HIPAA-covered organization with
Zero Data Retention enabled). The gateway exports this as `OPENAI_ORG_ID` at
startup so the OpenAI SDK (via litellm) forwards it on every request.

When unset, no organization is sent and OpenAI infers the org from the API key.

The `organization` field is also in `FORBIDDEN_REQUEST_PARAMS`, so caller-supplied
values are stripped — only the gateway-configured organization reaches OpenAI.

## Bedrock provider

AWS Bedrock is available as an alternative provider for the Anthropic endpoints.
Instead of dedicated routes, set the `X-PostHog-Provider: bedrock` header:

```http
X-PostHog-Provider: bedrock
```

Anthropic model names (e.g. `claude-sonnet-4-6`) are automatically mapped to Bedrock model IDs.
The gateway chooses the US or EU Bedrock profile based on `LLM_GATEWAY_BEDROCK_REGION_NAME` or the ambient AWS region.
You can also pass a Bedrock model ID directly (e.g. `us.anthropic.claude-sonnet-4-6`).

### Bedrock fallback

Set `X-PostHog-Use-Bedrock-Fallback: true` to automatically retry via Bedrock when the Anthropic provider returns a 5xx error:

```http
X-PostHog-Use-Bedrock-Fallback: true
```

The fallback only triggers on server errors (5xx), not client errors (4xx).
If both Anthropic and Bedrock fail, the original Anthropic error is returned.

### Configuration

To use Bedrock (either via `X-PostHog-Provider` or `X-PostHog-Use-Bedrock-Fallback`), configure one of:

- `LLM_GATEWAY_BEDROCK_REGION_NAME`
- `AWS_REGION`
- `AWS_DEFAULT_REGION`

Credentials are intentionally not loaded through `LLM_GATEWAY_*` settings in the gateway.
Use your runtime's standard AWS authentication mechanism (e.g. IAM role, IRSA, ECS task role, or pre-existing `AWS_*` env vars provisioned by deployment).

## Inference-provider routing

The gateway exposes models consistently across Anthropic Messages, chat/completions, and Responses while choosing their inference provider internally in `src/llm_gateway/inference_routing.py`.

- **GLM 5.2** (`@cf/zai-org/glm-5.2`) can run on Cloudflare Workers AI, Modal, or Baseten.
- **GLM 5.3** (`zai-org/glm-5.3`) runs only on Baseten and is available to ReviewHog and PostHog Desktop behind its own `posthog-code-glm-53-model` flag.
  Deliberately not `tasks-glm-baseten-inference`: that one only moves GLM 5.2 traffic onto Baseten, so sharing it would grant 5.3 by proxy the moment 5.2 routing changed.
  GLM 5.3 has no open weights released yet, so the flag is not created: the access gate fails closed, keeping the model blocked server-side and hidden in every picker.
  Do not create the flag until Baseten lists the model and the deployment slug, context window, and contract rate in `model_cost_overrides.py` / `model_registry.py` are confirmed against `inference.baseten.co/v1/models`: the rate is pinned, so a wrong placeholder bills at the wrong price with no automatic correction.
- **GLM 5.3 Flash** (`zai-org/glm-5.3-flash`) runs only on Baseten and is available to ReviewHog and PostHog Desktop behind its own `posthog-code-glm-53-flash-model` flag.
  Contract rate and 1M context window come from the Baseten listing and are pinned in `model_cost_overrides.py` / `model_registry.py`.
- **DeepSeek V4 Flash** (`deepseek-ai/deepseek-v4-flash-0731`) runs only on Baseten and is available to ReviewHog and PostHog Desktop (client-gated by the `posthog-code-deepseek-model` flag).

Provider configuration:

- **Cloudflare Workers AI** (the incumbent) — configure `LLM_GATEWAY_CLOUDFLARE_API_KEY` and `LLM_GATEWAY_CLOUDFLARE_ACCOUNT_ID`.
- **Modal** (an OpenAI-compatible vLLM endpoint) — configure `LLM_GATEWAY_MODAL_API_BASE`, `LLM_GATEWAY_MODAL_KEY`, and `LLM_GATEWAY_MODAL_SECRET` (a [Modal proxy-token](https://modal.com/docs/guide/endpoints) pair, sent as `Modal-Key`/`Modal-Secret` headers).
- **Baseten** (an OpenAI-compatible endpoint) - configure `LLM_GATEWAY_BASETEN_API_BASE` and `LLM_GATEWAY_BASETEN_API_KEY`.

The `tasks-glm-baseten-inference` feature flag routes matching users' GLM 5.2 traffic to Baseten when its API key is configured. The flag is evaluated server-side, and caller-forwarded flag headers cannot select Baseten. Cloudflare or Modal must remain configured as the fallback for users who do not match the flag or when evaluation is unavailable.

Two knobs opt traffic into Modal (OR semantics, both default off):

- The `tasks-glm-modal-inference` feature flag, evaluated server-side against PostHog (`LLM_GATEWAY_POSTHOG_PROJECT_TOKEN`/`_HOST`) with a short per-user cache and a brief global backoff when evaluation fails. Caller-forwarded flag headers are not trusted for routing.
- `LLM_GATEWAY_GLM_MODAL_TRAFFIC_FRACTION` (0..1, default 0), bucketed deterministically by user id; `LLM_GATEWAY_GLM_MODAL_PRODUCT_TRAFFIC_FRACTIONS` (e.g. `{"posthog_code": 0.25}`) overrides it per product.

If Cloudflare credentials are absent, Modal serves all GLM traffic regardless of the knobs.

There are no cross-backend retries: a Modal-side failure surfaces to the caller unchanged (each backend's health stays independently visible under its `provider` metric label), and rollback is turning the flag/fraction back down.
Smoke scripts: `scripts/glm_cf_smoke.py` (Cloudflare) and `scripts/glm_modal_smoke.py` (Modal).

## Products

Every request is scoped to a **product**. The product determines which models and auth methods are allowed, and is recorded as `ai_product` on `$ai_generation` events so you can filter costs per product.

### Registered products

Defined in `src/llm_gateway/products/config.py`:

OAuth access is permitted only for products with an explicit `allowed_application_ids` allowlist. All other products are API-key-only by default.

| Product              | Auth            | Models                     | Notes                           |
| -------------------- | --------------- | -------------------------- | ------------------------------- |
| `llm_gateway`        | API key only    | All                        | Default when no product in path |
| `ci`                 | API key only    | All                        | CI / e2e test runs              |
| `posthog_code`       | OAuth only      | Restricted set             | Desktop coding agent            |
| `background_agents`  | OAuth only      | Restricted set             | Cloud background agents         |
| `onboarding`         | OAuth only      | claude-sonnet-5            | Unbilled setup wizard cloud run |
| `wizard`             | API key + OAuth | All                        | Max AI assistant                |
| `django`             | API key only    | All                        | Server-side Django calls        |
| `growth`             | API key only    | All                        | Growth team                     |
| `llma_translation`   | API key only    | gpt-4.1-mini               | AI observability translation    |
| `llma_summarization` | API key only    | gpt-4.1-nano, gpt-4.1-mini | AI observability summarization  |
| `llma_eval_summary`  | API key only    | gpt-5-mini                 | AI observability eval summary   |

Aliases: `twig`, `array` resolve to `posthog_code`; `slack-twig` resolves to `slack-posthog-code`.

`posthog_code` additionally requires a project-scoped PostHog Desktop decision. The OAuth application allowlist only proves that the Desktop app issued the token. It does not grant Desktop access.

After OAuth validates the selected project, the gateway asks Django at `GET /api/projects/{project_id}/desktop/access/`. Django applies `posthog-desktop-access-override` before Startup-program and prepaid-credit restrictions. The gateway preserves `code_access_required` as its error code and forwards `startup_plan` or `prepaid_credits` when Django provides a reason. Server-minted credentials carrying `internal_run:read` bypass the human gate because their run already passed Django's trusted task path.

The check fails closed. Django transport errors, 404, 429, 5xx responses, and malformed payloads return `503 desktop_access_unavailable` and are not cached. Django 401 and 403 credential rejections return a generic `403 code_access_required` without a funding reason and cache for 30 seconds per credential and project to limit repeated rejected lookups. Deploy the Django project endpoint everywhere before deploying this gateway contract; old gateway instances continue using the compatibility endpoint during that rollout. The Gateway allows six seconds for Django because Django can spend up to five seconds resolving a Billing cache miss. Grants cache for 60 seconds and business denials for 30 seconds. Cache keys include the user, validated team, and a non-reversible credential fingerprint. Desktop access checks use a separate outbound connection pool, capped at 10 connections per Gateway instance, so failures cannot exhaust the pool used by other policy resolvers. `LLM_GATEWAY_DESKTOP_ACCESS_GATE_ENABLED=false` disables the gateway gate.

`signals` is authorized for its own OAuth application, so a Signals run's token cannot be spent as `posthog_code` or `background_agents` by declaring a different product in the path.
Its US, EU, and dev application ids are pinned in `products/config.py` alongside every other first-party app.
The PostHog Code application ids are no longer accepted for `signals`, so a region whose runs still mint under the Code app rejects every Signals OAuth run at the gateway.

### Adding a new product

1. **Add to `PRODUCTS`** in `src/llm_gateway/products/config.py`:

   ```python
   "my_product": ProductConfig(
       allowed_application_ids=frozenset({...}),  # empty/None = no OAuth apps allowed; list IDs to permit OAuth
       allowed_models=None,                       # None = all models, or frozenset({...}) to restrict
       allow_api_keys=True,                       # False = OAuth only
   ),
   ```

2. **Add to `Product` type** in `posthog/llm/gateway_client.py` (if calling from Django).

3. **Route requests** to `/{my_product}/v1/...` — the gateway extracts the product from the URL path.

That's it. Rate limiting defaults apply automatically (see below).

## Rate limiting

Cost-based rate limiting is applied at two levels: **product-level** (shared across all users) and **user-level** (per end-user within a product).

### Product-level limits

A global cost cap for the entire product. Configured in `DEFAULT_PRODUCT_COST_LIMITS` in `src/llm_gateway/config.py`:

```python
"my_product": ProductCostLimit(limit_usd=1000.0, window_seconds=3600)  # $1000/hour
```

Products without an explicit entry fall back to **$1000 per 24 hours**.

### User-level limits

Per-user cost caps using a burst + sustained pattern. Configured in `DEFAULT_USER_COST_LIMITS` in `src/llm_gateway/config.py`:

```python
"my_product": UserCostLimit(
    burst_limit_usd=100.0,        # Short-term cap
    burst_window_seconds=86400,   # 24 hours
    sustained_limit_usd=1000.0,   # Long-term cap
    sustained_window_seconds=2592000,  # 30 days
)
```

Products without an explicit entry fall back to the **default: $100/24h burst, $1000/30d sustained**.

User-level limits only apply when an `end_user_id` is present (OAuth token holder, or `user` param in the request body).

### Per-run limits

A sandbox agent run can spend a whole window's budget in one conversation, because the person driving it decides when it ends.
`DEFAULT_SANDBOX_TASK_COST_LIMITS` caps the total spend of a single run, keyed on the task the token was minted for (`posthog_oauthaccesstoken.sandbox_task_id`), not on anything the caller sends:

```python
"my_budget": ProductCostLimit(limit_usd=50.0, window_seconds=604800)  # $50 per run
```

Opt-in — a budget with no entry has no per-run ceiling, and a token with no task binding is never metered here.

### Budget keys

The three limits above are usually keyed by product, but a product that serves both our own scheduled work and a button a customer can press needs two budgets rather than one.
`resolve_cost_key` picks the budget from the token's scopes, which are minted server-side, instead of from the product in the URL, which the caller chooses.

Today that splits `signals`: a run started from the Inbox carries `interactive_run:read` and meters against `signals_interactive`, while the scheduled pipeline keeps `signals`.
`signals_interactive` is a budget name only — it is not in `PRODUCTS`, so no caller can request it.

## Error handling

Errors follow OpenAI's format:

```json
{
  "error": {
    "message": "Rate limit exceeded",
    "type": "rate_limit_error",
    "code": "rate_limit_exceeded"
  }
}
```

| Status | Meaning                                     |
| ------ | ------------------------------------------- |
| 400    | Bad request (invalid model, missing fields) |
| 401    | Invalid or missing API key                  |
| 403    | Insufficient scope or unauthorized product  |
| 429    | Rate limit exceeded                         |
| 504    | Request timeout                             |

## Internal Django integration

For calling from PostHog Django:

```python
from posthog.llm.gateway_client import get_llm_client

# Pass `team_id` to attribute the captured `$ai_generation` event to a specific
# customer team: it sets the `x-posthog-property-team_id` header on every request so
# the usage reporter can break cost down per customer (the gateway PAK owns a single
# internal team). Omit it to attribute to the key owner's team (the default).
client = get_llm_client(product="my_product", team_id=team.id)
response = client.chat.completions.create(
    model="claude-opus-4-5",  # or any supported OpenAI, Anthropic, OpenRouter, or Fireworks AI model
    messages=[...],
    user=request.user.distinct_id,  # user for analytics and rate limiting
)
```

`ai_product` and `$ai_billable` are derived from the product config (`products/config.py`):
the route sets `ai_product` from the `product` arg, and `$ai_billable` from whether that
product has a `credit_bucket`. Set `credit_bucket` on the product config to bill its
generations into that bucket; leave it `None` to keep them unbilled.
