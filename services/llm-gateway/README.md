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
  -H "Authorization: Bearer phx_your_personal_api_key" \
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

Products: `llm_gateway` (default), `twig`, `wizard`, `django`

## Supported models

All OpenAI, Anthropic and Gemini chat models are supported.

## Rate limiting

Cost-based rate limiting is applied per user and per product, and you can specify custom rate limits for your product in it's config.

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
