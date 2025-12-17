# LLM Gateway

A standalone microservice for proxying LLM requests to Anthropic, OpenAI, and Google Gemini APIs using unified endpoints.

## Configuration

All environment variables are prefixed with `LLM_GATEWAY_` - you can find them in `src/llm_gateway/config.py`

Key configuration variables:

- `LLM_GATEWAY_ANTHROPIC_API_KEY` - Anthropic API key (optional, only needed for Claude models)
- `LLM_GATEWAY_OPENAI_API_KEY` - OpenAI API key (optional, only needed for GPT models)
- `LLM_GATEWAY_GEMINI_API_KEY` - Google Gemini API key (optional, only needed for Gemini models)

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

#### Using Gemini models

```bash
# Basic text completion
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer phx_your_personal_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini/gemini-3-pro-preview",
    "messages": [{"role": "user", "content": "Hello"}]
  }'

# Vision example
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer phx_your_personal_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini/gemini-3-flash-preview",
    "messages": [{
      "role": "user",
      "content": [
        {"type": "text", "text": "What'\''s in this image?"},
        {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
      ]
    }]
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
