# LLM Gateway

A standalone microservice for proxying LLM requests to Anthropic and OpenAI APIs using unified endpoints.

## Configuration

All environment variables are prefixed with `LLM_GATEWAY_` - you can find them in `src/llm_gateway/config.py`

## API Usage

Both endpoints support using all models, so e.g. you can use anthropic models with the OpenAI compatible endpoint, and vica versa.

If you do not require a specific endpoint format, the OpenAI Chat Completions one is the most popular format and is the recommended one to use.

### OpenAI-compatible endpoint

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer phx_your_personal_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

### Anthropic-compatible endpoint

```bash
curl -X POST http://localhost:8080/v1/messages \
  -H "Authorization: Bearer phx_your_personal_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```
