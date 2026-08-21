# Signals agentic evals

These suites compare models on research, repository selection, implementation, and scout runs.
They use the production Signals entry points and report to Braintrust.

## Setup

Add these to `.env`:

```dotenv
BRAINTRUST_API_KEY=...
ANTHROPIC_API_KEY=...
SANDBOX_JWT_PRIVATE_KEY=...
```

Use `OPENAI_API_KEY` instead of `ANTHROPIC_API_KEY` for Codex runs.

## Run locally

List all discovered suites:

```bash
hogli evals --list
```

Run one case:

```bash
hogli evals signals/eval_research \
  --eval research_checkout_timeout \
  --max-sandboxes 1
```

Run a full step:

```bash
hogli evals signals/eval_research --max-sandboxes 2
hogli evals signals/eval_repository_selection --max-sandboxes 2
hogli evals signals/eval_implementation --max-sandboxes 2
hogli evals signals/eval_scout --max-sandboxes 2
```

Run a model arm:

```bash
hogli evals signals/eval_research \
  --agent-runtime codex \
  --agent-model gpt-5.5 \
  --reasoning-effort high \
  --trials 3 \
  --max-sandboxes 2
```

The suite IDs are:

- `signals/eval_research::eval_research`
- `signals/eval_repository_selection::eval_repository_selection`
- `signals/eval_implementation::eval_implementation`
- `signals/eval_scout::eval_scout`

## Braintrust results

All four steps report to the `signals-agentic` Braintrust project. Case metadata records the step,
and experiment metadata records the runtime, model, and reasoning effort.

Each case records its input, output, scores, model turns, tool calls, duration, tokens, and cost.
Braintrust aggregates the metrics per experiment. Research, implementation, and scout include an LLM
quality judge. Implementation grades the diff captured from the task log. Scout grades persisted
reports, signals, and scratchpad writes. Scout cases run the canonical scout skills against seeded
project events and objects.

Repository-selection cases use deterministic metadata for public repositories and do not depend on
an engineer's GitHub account.

## Architecture

The shared `WorkflowPublicEval` owns setup, concurrency, cleanup, logs, trials, and reporting. This
package owns:

- curated synthetic cases and expectations;
- adapters that call the Signals production workflows;
- deterministic seed data required by a specific step;
- Signals-specific deterministic and judged scorers.
