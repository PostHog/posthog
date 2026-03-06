# LLMA Eval Framework

## Structure

- `products/signals/eval/framework.py` — core: `EvalCase`, `EvalMetric`, `run_eval()`
- `products/signals/eval/conftest.py` — pytest fixtures: `posthog_client`, `openai_client`
- `products/signals/eval/test_joke_eval.py` — reference example with two evals

## How it works

Each eval has three parts:

1. **Task function** — runs the LLM call being evaluated
2. **Judge function** — scores the output using a stronger LLM, returns JSON with score + reasoning
3. **Cases** — list of `EvalCase(name, input, expected)` defining test inputs

`run_eval()` is async and runs all cases concurrently (bounded by `max_concurrency`, default 10) using `asyncio.gather`. Errors are caught — pytest always passes.
By default (`verbose=True`), each case logs the task output, thoughts (if present), and judge reasoning alongside the score.

## Rules

- All task and judge functions must be `async`
- Use `@pytest.mark.django_db` on test functions
- Pass `posthog_distinct_id="llma_eval"` to all LLM calls
- Use a production model for the task, a strong reasoning model for the judge
- `experiment_name` and `EvalCase.name` must be unique
- Judge LLM must return JSON — parse with `json.loads()`
- `openai_client` fixture is `AsyncOpenAI`; for Gemini use `AsyncGeminiClient(posthog_client=client._ph_client)`
- Judge JSON must put `"reasoning"` before the score field (e.g. `{"reasoning": "...", "correct": true}`) — this forces the model to analyze before committing to a score
- Judge prompt must include a rubric with explicit per-level definitions and one anchor example per level (e.g. an example ACTIONABLE ticket and an example NOT_ACTIONABLE ticket) — this is the single highest-impact lever for judge consistency
- If the production flow uses a reasoning model or has thinking/chain-of-thought enabled, the task function should return thoughts alongside the answer (e.g. `{"answer": "...", "thoughts": "..."}`) and the judge prompt should include them — this lets the judge catch cases where the model got the right answer for the wrong reason

## Running

```bash
# Run all cases
pytest products/signals/eval/eval_<name>.py -s -v --log-cli-level=WARNING

# Run specific cases only
pytest products/signals/eval/eval_<name>.py --case-ids=00005,00010 -s -v --log-cli-level=WARNING
```

Requires `POSTHOG_PROJECT_API_KEY` (`phc_` prefix) and relevant AI provider keys in `.env`.
Events go to `POSTHOG_HOST` (default `http://localhost:8010`).

## Maintaining this document

If you change the eval framework (fixtures, `run_eval` signature, `EvalMetric` fields, conventions), update this file to match.
