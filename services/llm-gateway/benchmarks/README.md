# LLM Gateway Benchmarks

Measures the overhead the PostHog LLM gateway adds compared to calling providers directly.

## Metrics

- **TTFT** — Time to first token (streaming only)
- **TPS** — Tokens per second (streaming only)
- **Total latency** — End-to-end request time

Each metric is collected for both direct provider calls and gateway-proxied calls, then compared.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys
```

## Usage

```bash
# Quick connectivity check
python benchmark.py --iterations 1 --warmup 0 --models gpt-4.1-nano

# Full run with defaults (5 iterations, 1 warmup, all models)
python benchmark.py

# More iterations for stable numbers
python benchmark.py --iterations 10

# Test under concurrent load
python benchmark.py --concurrency 5 --iterations 3

# Only streaming or non-streaming
python benchmark.py --streaming-only
python benchmark.py --non-streaming-only

# Specific models
python benchmark.py --models gpt-4.1-mini claude-haiku-4-5-20251001

# Custom prompt and token limit
python benchmark.py --prompt "Explain quantum computing" --max-tokens 500

# Re-print saved results without re-running
python benchmark.py --report results/benchmark_20260213_143000.json
```

## Default models

| Model | Provider |
|---|---|
| gpt-4.1-mini | OpenAI |
| gpt-4.1-nano | OpenAI |
| claude-sonnet-4-5-20250514 | Anthropic |
| claude-haiku-4-5-20251001 | Anthropic |

## Output

Results are printed as a comparison table showing mean / median / p95 for each metric, with an overhead row showing the absolute and percentage delta between direct and gateway calls.

Raw results are saved as JSON to `results/` (gitignored) after each run for later review with `--report`.
