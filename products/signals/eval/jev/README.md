# Jev-compatible signal evals

This runner evaluates a Jev-like one-shot API against the labeled Signals corpora:

- 92 actionability cases
- 118 signal safety cases
- 60 report safety cases

Run commands from the repository root.

## Endpoint contract

The runner sends a JSON object with `state` and `questions`:

```json
{
  "state": {
    "policy": "...",
    "signal": "..."
  },
  "questions": {
    "safe": {
      "type": "noul",
      "instructions": "Is this signal safe under the policy?"
    }
  }
}
```

The response must return the answer probability under `answers.<name>.noul`:

```json
{
  "model": "example-model",
  "answers": {
    "safe": {
      "noul": 0.98
    }
  },
  "usage": {
    "input_tokens": 412,
    "output_tokens": 1
  }
}
```

`model` and `usage` are optional. Token usage is required for cost estimates.

## Run against an endpoint

Use a Bearer token:

```bash
JEV_API_URL=https://example.com/v1/systemone \
JEV_API_KEY=... \
pytest products/signals/eval/eval_jev.py --no-capture
```

Or use HTTP Basic authentication:

```bash
JEV_API_URL=https://example.com/v1/systemone \
JEV_USERNAME=... \
JEV_PASSWORD=... \
pytest products/signals/eval/eval_jev.py --no-capture
```

Leave both authentication methods unset for an endpoint that does not require authentication. Secrets can also be supplied through `op run` or another environment manager.

For a quick smoke test, `--limit 5` runs five cases from each task. Set `JEV_CONCURRENCY` to control parallel requests. The default is one request at a time.

## Export requests without calling an endpoint

```bash
JEV_EXPORT_PATH=/tmp/signals-jev-evals.jsonl \
pytest products/signals/eval/eval_jev.py --no-capture
```

Each JSONL row contains a case ID, task, request body, and expected answer. The object under `request` can be posted directly to a compatible endpoint.

## Thresholds and cost

The default decision threshold is `0.5`. Override it per task with:

- `JEV_ACTIONABILITY_THRESHOLD`
- `JEV_SIGNAL_SAFETY_THRESHOLD`
- `JEV_REPORT_SAFETY_THRESHOLD`

Set `JEV_INPUT_USD_PER_MILLION` and `JEV_OUTPUT_USD_PER_MILLION` to calculate estimated cost from the endpoint's token usage.

The summary reports correctness, false positives, false negatives, errors, p50 and p95 latency, request size, token usage, and estimated cost. Per-case results are written to `products/signals/eval/cache/jev_results.json`, which is ignored by Git.
