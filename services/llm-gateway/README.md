# LLM Gateway

A standalone microservice for proxying LLM requests to Anthropic, OpenAI, and Google Gemini APIs.

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

When running via mprocs, a personal API key with the `llm_gateway:read` scope is **automatically provisioned** on startup.
The key is deterministic and survives database resets:

```text
phx_dev_local_test_api_key_1234567890abcdef
```

You can use this key directly to make requests to the gateway locally.
It is also available as `settings.DEV_API_KEY` in Django.

In local dev (`DEBUG=True`), the gateway client defaults to `http://localhost:3308` and this key,
so `get_llm_client()` works out of the box without setting any environment variables.

You can also provision the key manually:

```bash
python manage.py setup_local_api_key --add-scopes llm_gateway:read
```

`--add-scopes` merges into existing scopes without removing any.
`--scopes` replaces all scopes on the key.

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

## API endpoints

### OpenAI-compatible

- `POST /v1/chat/completions` - Chat completions
- `POST /v1/responses` - OpenAI Responses API

### Anthropic-compatible

- `POST /v1/messages` - Anthropic Messages API

### Product-scoped endpoints

For product-specific rate limits and tracking:

- `POST /{product}/v1/chat/completions`
- `POST /{product}/v1/messages`

The product name is extracted from the first path segment and recorded as `ai_product` on `$ai_generation` events. See [Products](#products) for the full list and how to add one.

## Supported models

All OpenAI, Anthropic and Gemini chat models are supported.

## Products

Every request is scoped to a **product**. The product determines which models and auth methods are allowed, and is recorded as `ai_product` on `$ai_generation` events so you can filter costs per product.

### Registered products

Defined in `src/llm_gateway/products/config.py`:

| Product              | Auth            | Models                     | Notes                           |
| -------------------- | --------------- | -------------------------- | ------------------------------- |
| `llm_gateway`        | API key + OAuth | All                        | Default when no product in path |
| `twig`               | OAuth only      | Restricted set             | Desktop coding agent            |
| `background_agents`  | OAuth only      | Restricted set             | Cloud background agents         |
| `wizard`             | OAuth only      | All                        | Max AI assistant                |
| `django`             | API key + OAuth | All                        | Server-side Django calls        |
| `growth`             | API key + OAuth | All                        | Growth team                     |
| `llma_translation`   | API key + OAuth | gpt-4.1-mini               | LLM analytics translation       |
| `llma_summarization` | API key + OAuth | gpt-4.1-nano, gpt-4.1-mini | LLM analytics summarization     |
| `llma_eval_summary`  | API key + OAuth | gpt-5-mini                 | LLM analytics eval summary      |

Aliases: `array` resolves to `twig`.

### Adding a new product

1. **Add to `PRODUCTS`** in `src/llm_gateway/products/config.py`:

   ```python
   "my_product": ProductConfig(
       allowed_application_ids=None,  # None = any OAuth app, or frozenset({...}) to restrict
       allowed_models=None,           # None = all models, or frozenset({...}) to restrict
       allow_api_keys=True,           # False = OAuth only
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

client = get_llm_client()
response = client.chat.completions.create(
    model="claude-opus-4-5",  # or any supported OpenAI, Anthropic or Gemini model
    messages=[...],
    user=request.user.distinct_id,  # user for analytics and rate limiting
)
```
