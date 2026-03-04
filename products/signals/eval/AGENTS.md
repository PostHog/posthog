# LLMA Eval Framework

## Structure

- `products/signals/eval/framework.py` — core: `EvalCase`, `EvalMetric`, `run_eval()`
- `products/signals/eval/conftest.py` — pytest fixtures: `posthog_client`, `openai_client`
- `products/signals/eval/test_joke_eval.py` — reference example with two evals

## How it works

Each eval has three parts:

1. **Task function** `(client: OpenAI, case: EvalCase) -> Any` — runs the LLM call being evaluated
2. **Judge function** `(client: OpenAI, case: EvalCase, output) -> EvalMetric` — scores the output using a stronger LLM, returns JSON with score + reasoning
3. **Cases** — list of `EvalCase(name, input, expected)` defining test inputs

`run_eval()` orchestrates: runs task per case, runs judge, sends `$ai_evaluation` events to PostHog, prints summary. Errors are caught — pytest always passes.

## Rules

- Use `@pytest.mark.django_db` on test functions
- Pass `posthog_distinct_id="llma_eval"` to all `client.chat.completions.create()` calls
- Use different model families for generation and judging to avoid self-evaluation bias
- `experiment_name` and `EvalCase.name` must be unique
- Judge LLM must return JSON — parse with `json.loads()`
- Judge JSON must put `"reasoning"` before the score field (e.g. `{"reasoning": "...", "correct": true}`) — this forces the model to analyze before committing to a score
- Judge prompt must include a rubric with explicit per-level definitions and one anchor example per level (e.g. an example ACTIONABLE ticket and an example NOT_ACTIONABLE ticket) — this is the single highest-impact lever for judge consistency

## Running

```bash
pytest products/signals/eval/test_<name>.py -s -v
```

Requires `POSTHOG_PROJECT_API_KEY` (`phc_` prefix) in `.env`.
Events go to `POSTHOG_HOST` (default `http://localhost:8010`).

## Maintaining this document

If you change the eval framework (fixtures, `run_eval` signature, `EvalMetric` fields, conventions), update this file to match.
