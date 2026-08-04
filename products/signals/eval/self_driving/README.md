# Signals self-driving eval

This benchmark measures the complete Signals workflow from synthetic customer evidence to an implemented code change:

```text
signals and product events -> researched report -> implementation task -> verified patch
```

It runs the real local PostHog stack, including Temporal, Postgres, ClickHouse, the MCP server, and Docker sandboxes. The customer repositories and telemetry are synthetic, so the benchmark is repeatable and does not need access to customer data or GitHub repositories.

The suite currently contains 12 tasks across logic, API, frontend state, performance, data integrity, and configuration defects. Each task has a fixture repository, realistic signals, seeded telemetry, ground truth, and hidden behavioral tests.

## How this fits with the other evals

This suite stays under `products/signals/eval/` because it exercises a full product workflow. The shared harness under `products/posthog_ai/eval_harness/` currently supports direct sandbox-agent and one-shot model cases, while this benchmark needs Signals workflows to create and advance reports before an implementation task exists.

It follows the same core conventions:

- one Braintrust case per task and trial;
- isolated data for every case;
- deterministic scorers where possible and model judges only for qualitative dimensions;
- bounded case concurrency and explicit stage timeouts;
- JSON-serializable inputs, outputs, metadata, and scores;
- product-owned fixtures and scorers.

The existing grouping and scout evals cover individual Signals stages. This suite complements them by testing the whole autonomous loop.

## Quick validation

Validate the task contracts and hidden tests without starting the local stack or making model calls:

```bash
.codex/with-flox hogli test products/signals/backend/test/test_self_driving_eval.py
```

For every pristine fixture, this checks that the planted-fix tests fail, the regression tests pass, and the task metadata is complete.

## Full run

### 1. Prepare the environment

From the repository root:

```bash
.codex/with-flox --prepare true
export SELFDRIVING_EVAL_WORKSPACE=/tmp/selfdriving-eval-workspace
export SANDBOX_REPO_MOUNT_MAP="$(.codex/with-flox python -c 'from products.signals.eval.self_driving.harness.drive import print_mount_map; print_mount_map()')"
```

The mount map must be present when the Temporal worker starts. Local Docker sandboxes recognize these mapped repositories, skip GitHub authentication, and allow unsigned local commits. This behavior is available only with `DEBUG=1` and the Docker sandbox provider.

### 2. Start the local stack

```bash
.codex/with-flox hogli start -y -d
.codex/with-flox hogli wait
```

The selected development profile must include Temporal workflows, the MCP server, ClickHouse, personhog, and the Django web process. Confirm these endpoints before starting an expensive run:

```bash
curl --fail http://localhost:8000/_health
curl --fail http://localhost:8787/mcp
```

The MCP endpoint may return a non-2xx protocol response to a plain GET. A response still confirms that the server is reachable.

### 3. Run a smoke case

Start with one task and one trial:

```bash
.codex/with-flox python manage.py run_self_driving_eval \
    --task checkout-coupon-case \
    --trials 1 \
    --parallelism 1 \
    --experiment-name self-driving-smoke
```

After the smoke case succeeds, omit `--task` to run all tasks:

```bash
.codex/with-flox python manage.py run_self_driving_eval \
    --trials 1 \
    --parallelism 2 \
    --experiment-name self-driving-full
```

Use `python manage.py run_self_driving_eval --help` for timeout and workspace options.

## Required configuration

The standard PostHog development environment supplies the local service URLs. A full run also needs:

| Setting                          | Purpose                                                                    |
| -------------------------------- | -------------------------------------------------------------------------- |
| `BRAINTRUST_API_KEY`             | Records cases, metadata, and scores in the `signals-self-driving` project. |
| `LLM_GATEWAY_API_KEY`            | Authenticates model calls through the internal LLM gateway.                |
| `LLM_GATEWAY_ANTHROPIC_API_KEY`  | Lets the local gateway call the agent and judge models.                    |
| `SANDBOX_JWT_PRIVATE_KEY`        | Authenticates local sandbox connections.                                   |
| `CLICKHOUSE_DATABASE=posthog`    | Selects the local ClickHouse database.                                     |
| `PERSONHOG_ADDR=localhost:50052` | Enables person and group lookups from the worker.                          |

Do not put credentials in task fixtures, result files, commits, or Braintrust metadata.

## Results

Braintrust receives one row per task and trial in the `signals-self-driving` project. The row includes research, implementation, and end-to-end scores. See [DESIGN.md](DESIGN.md) for the scorer definitions.

Raw pipeline results are also written to:

```text
$SELFDRIVING_EVAL_WORKSPACE/results/<task-id>-t<trial>.json
```

Materialized repositories and local bare remotes stay in the workspace for inspection. A new run recreates each selected repository before the agent starts.

## Task selection

Available task IDs come from `tasks/*/task.json`. List them with:

```bash
.codex/with-flox python manage.py run_self_driving_eval --help
```

Repeat `--task` to run a subset:

```bash
.codex/with-flox python manage.py run_self_driving_eval \
    --task checkout-coupon-case \
    --task signup-email-normalize
```

## Adding or changing a task

Read [TASK_SPEC.md](TASK_SPEC.md), then add or update the task under `tasks/<task-id>/`. Run the quick validation before a full smoke case. A useful task must meet all of these conditions:

- the pristine repository fails every fix test;
- the pristine repository passes every regression test;
- a correct implementation can pass both groups;
- signals describe symptoms without revealing the planted cause;
- seeded event names match the repository's instrumentation;
- ground truth describes observable behavior, evidence, and plausible distractors.

## Troubleshooting

`Repository ... is not present in the sandbox` usually means the Temporal worker started without `SANDBOX_REPO_MOUNT_MAP`. Export the map, restart the stack, and rerun the case.

GitHub authentication should not run for mapped fixture repositories. If it does, confirm `DEBUG=1`, `SANDBOX_PROVIDER=docker`, and that the workspace path exists when the implementation activity begins.

If research produces no findings, check the MCP server and `PERSONHOG_ADDR`. If the implementation never starts, inspect the report status and actionability and priority artifacts in the raw result.

The first sandbox run may take several minutes while the local image is built. The fixture verification tests use only language standard libraries and do not install package dependencies.
