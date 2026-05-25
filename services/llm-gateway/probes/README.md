# LLM Gateway Provider Probes

One-shot scripts that answer "can LiteLLM, pinned at the version we use in production, talk to this provider in our gateway's two wire formats?" — before we wire the provider into the gateway proper.

## probe_cloudflare_kimi.py

Validates Cloudflare Workers AI's Kimi K2.6 (`@cf/moonshotai/kimi-k2.6`) end-to-end via `litellm.anthropic_messages` and `litellm.acompletion`, including tool calls and streaming.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in CLOUDFLARE_API_KEY + CLOUDFLARE_ACCOUNT_ID
python probe_cloudflare_kimi.py             # both routings
python probe_cloudflare_kimi.py --routing native --verbose
```

The probe tries two LiteLLM routings against the same model:

- **native**: `cloudflare/@cf/moonshotai/kimi-k2.6` (uses LiteLLM's bundled Cloudflare provider)
- **openai-compat**: `openai/@cf/moonshotai/kimi-k2.6` with `api_base` pointing at `https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/v1`

For each routing it runs four checks:

1. `acompletion` baseline (OpenAI format) — proves the model is reachable at all
2. `anthropic_messages` plain text — does LiteLLM's Anthropic adapter translate the response?
3. `anthropic_messages` with a tool — does `tool_use` round-trip cleanly?
4. `anthropic_messages` streaming — does the SSE produce real Anthropic events (`message_start`, `content_block_*`, `message_stop`)?

Exit code is 0 if at least one routing passes every check. Interpret the output:

- All four pass on **either** routing → integration is mostly a config change in `services/llm-gateway/src/llm_gateway/` (mirror the Fireworks pattern).
- Checks 1–2 pass but 3 (tool) or 4 (stream) fails → we need a thin Anthropic↔OpenAI adapter in the gateway for the failing path. Check 1's success bounds the worst case: we can always fall back to translating ourselves on top of `acompletion`.
- Check 1 fails → credentials or model availability problem; fix that first.

## Getting Cloudflare credentials

1. CF dashboard → your account → **AI** → **Workers AI** → **REST API** → create a token with the `Workers AI > Read` permission.
2. Account ID is shown on the same page, or in any dashboard URL: `dash.cloudflare.com/<ACCOUNT_ID>/...`.

The token only needs Workers AI permissions; do not reuse a global API key.
