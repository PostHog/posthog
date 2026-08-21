# Signals agentic evals

These suites compare models on four Signals pipeline steps: research, repository selection,
implementation, and scout triage. They use the shared PostHog eval harness and report every run to
Braintrust.

## Setup

Add these to `.env`:

```dotenv
BRAINTRUST_API_KEY=...
ANTHROPIC_API_KEY=...
SANDBOX_JWT_PRIVATE_KEY=...
```

Codex runs also require `OPENAI_API_KEY`.

## Run locally

List all discovered suites:

```bash
./bin/hogli evals --list
```

Run one case:

```bash
./bin/hogli evals signals/eval_research \
  --eval research_checkout_timeout \
  --max-sandboxes 1
```

Run a full step:

```bash
./bin/hogli evals signals/eval_research --max-sandboxes 2
./bin/hogli evals signals/eval_repository_selection --max-sandboxes 2
./bin/hogli evals signals/eval_implementation --max-sandboxes 2
./bin/hogli evals signals/eval_scout --max-sandboxes 2
```

Run a model arm:

```bash
./bin/hogli evals signals/eval_research \
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

Each case records its input, expected target, structured output, task log, duration, runtime/model
metadata, and scores. Research, implementation, and scout also have an LLM quality judge.
Implementation grades the diff captured from the task log.

Repository-selection cases use deterministic metadata for public repositories and do not depend on
an engineer's GitHub account.

## Architecture

The shared `WorkflowPublicEval` owns setup, concurrency, timeouts, cleanup, logs, trials, and
Braintrust reporting. This package owns:

- curated synthetic cases and expectations;
- small adapters that call the real Signals production workflows;
- deterministic seed data required by a specific step;
- Signals-specific deterministic and judged scorers.

There is no replay or cassette mode.
