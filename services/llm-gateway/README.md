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

| Method | Token Prefix | Header |
|--------|--------------|--------|
| Personal API Key | `phx_` | `Authorization: Bearer phx_...` or `x-api-key: phx_...` |
| OAuth Access Token | `pha_` | `Authorization: Bearer pha_...` |

**Required Scope**: `llm_gateway:read`

## User attribution

When calling the gateway on behalf of end-users, **always specify the end-user's identifier**:

### OpenAI SDK (Python)

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://llm-gateway.posthog.com/v1",
    api_key="phx_your_api_key",
)

response = client.chat.completions.create(
    model="gpt-4.1-mini",
    messages=[{"role": "user", "content": "Hello"}],
    user="user_distinct_id_123",  # End-user attribution
)
```

### OpenAI SDK (TypeScript/JavaScript)

```typescript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'https://llm-gateway.posthog.com/v1',
  apiKey: 'phx_your_api_key',
});

const response = await client.chat.completions.create({
  model: 'gpt-4.1-mini',
  messages: [{ role: 'user', content: 'Hello' }],
  user: 'user_distinct_id_123',  // End-user attribution
});
```

### Anthropic SDK (Python)

```python
import anthropic

client = anthropic.Anthropic(
    base_url="https://llm-gateway.posthog.com/v1",
    api_key="phx_your_api_key",
)

response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello"}],
    metadata={"user_id": "user_distinct_id_123"},  # End-user attribution
)
```

### How attribution works

| Field | Description | PostHog Event Property |
|-------|-------------|----------------------|
| `user` (OpenAI) / `metadata.user_id` (Anthropic) | End-user identifier | `distinct_id`, `$ai_trace_id` |
| API Key owner | Team/billing attribution | `groups.project` |

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

Products: `llm_gateway` (default), `array`, `wizard`, `django`

## Supported models

All models are available via any endpoint format:

- **OpenAI**: `gpt-4.1`, `gpt-4.1-mini`, `gpt-4o`, `o3-mini`, etc.
- **Anthropic**: `claude-sonnet-4-20250514`, `claude-3-5-sonnet`, etc.
- **Google**: `gemini/gemini-3-pro-preview`, etc.

## Rate limiting

Cost-based rate limiting is applied per user and per product:

- Default: $500/hour per user
- Limits configurable per product

Rate limit headers are included in responses.

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

| Status | Meaning |
|--------|---------|
| 400 | Bad request (invalid model, missing fields) |
| 401 | Invalid or missing API key |
| 403 | Insufficient scope or unauthorized product |
| 429 | Rate limit exceeded |
| 504 | Request timeout |

## Configuration

Environment variables (prefix `LLM_GATEWAY_`):

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection URL (required) |
| `REDIS_URL` | Redis URL for rate limiting (optional) |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `GEMINI_API_KEY` | Google Gemini API key |
| `POSTHOG_API_KEY` | PostHog API key for analytics |
| `POSTHOG_HOST` | PostHog host URL |

## Internal Django integration

For calling from PostHog Django:

```python
from posthog.llm.gateway_client import get_llm_client

client = get_llm_client(team_id=team.id)
response = client.chat.completions.create(
    model="gpt-5-mini",  # or any supported model
    messages=[...],
    user=request.user.distinct_id,  # Always pass for attribution
)
```

### Supported models

- **OpenAI**: `gpt-5.2`, `gpt-5-mini`, `gpt-5-nano`
- **Anthropic**: `claude-opus-4-5`, `claude-sonnet-4-5`, `claude-haiku-4-5`

### Fallback behavior

When the gateway is disabled (feature flag off or unavailable), the client transparently maps Anthropic models to OpenAI equivalents:

| Anthropic | OpenAI fallback |
|-----------|-----------------|
| `claude-opus-4-5` | `gpt-5.2` |
| `claude-sonnet-4-5` | `gpt-5-mini` |
| `claude-haiku-4-5` | `gpt-5-nano` |

Uses feature flag `use-llm-gateway` to control gateway vs direct OpenAI.
