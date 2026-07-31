# Sandboxed agent evals

These evals run the real coding agent inside a real sandbox against a seeded Hedgebox project, then score what it did.
Each eval case gets its own isolated org/team/user, so cases never see each other's state.

Unlike `ee/hogai/eval/ci/`, this tree does **not** run under pytest.
It runs on a standalone harness that boots the shared infrastructure once (test database, Django live server, LLM gateway, MCP server, Temporal) and then runs every selected suite concurrently.
See [`harness/README.md`](harness/README.md) for how that works internally.

The harness also hosts non-sandboxed suite kinds — see [Suite kinds](#suite-kinds).
A run boots only the infrastructure its selected suites need, so a one-shot-only run starts no sandbox provider, Temporal, live server, LLM gateway, or MCP server.

Two other docs sit next to this one:

- [`../evals/AGENTS.md`](../evals/AGENTS.md) is the Hedgebox dataset reference. Read it before writing eval cases: your `expected` values and scorers must match that taxonomy exactly.
- [`harness/AGENTS.md`](harness/AGENTS.md) lists the invariants to preserve when changing the harness itself.

## Running

```bash
hogli evals [SELECTOR ...] [flags]
```

`hogli evals:sandboxed` is a back-compat alias of `hogli evals`; both run the same harness.

Run it from a flox shell — the personhog build needs flox's Rust toolchain (`cargo`, `pkg-config`, OpenSSL), and outside it the preflight build fails.

Or invoke the harness module directly:

```bash
python -m products.posthog_ai.eval_harness.harness [SELECTOR ...] [flags]
```

No manual env sourcing is needed on either path.
The harness loads the repo-root `.env` itself (shell values win), and `hogli evals` additionally layers in `.env.local` / `.env.development` / `.env.services` through hogli's standard env loading — including 1Password resolution when `.env.local` holds `op://` references.
Before any infrastructure boots, a preflight validates that the required variables are set and fails with a one-line fix per missing variable.
Which variables are required depends on the eval engine and the selected suites' kinds: the braintrust engine (the default, and only one today) requires `BRAINTRUST_API_KEY` on every run — it is the engine's own `required_env()`, not a core harness variable; sandboxed suites add `SANDBOX_JWT_PRIVATE_KEY` and `LLM_GATEWAY_ANTHROPIC_API_KEY`; one-shot suites add `LLM_GATEWAY_ANTHROPIC_API_KEY` (used directly, no gateway).

Selectors are substrings matched against a suite id of the form `<domain>/<module>::<fn>`, for example `experiments`, `sql`, or `eval_lifecycle_skills`.
Omit them to run every suite.
An unmatched selector fails immediately, before anything is provisioned.

The harness needs the Rust toolchain (`cargo`, provided by the flox shell): person and group reads go through personhog with no ORM fallback, so it builds and runs `personhog-replica` + `personhog-router` from `rust/` against the test persons DB.
The first build compiles the crates and can take several minutes; later builds are incremental no-ops.

```bash
# every suite, docker sandboxes, 4 at a time
python -m products.posthog_ai.eval_harness.harness

# two domains
python -m products.posthog_ai.eval_harness.harness experiments sql

# one suite, one case
python -m products.posthog_ai.eval_harness.harness eval_sql --eval churn

# remote sandboxes, every case at once
python -m products.posthog_ai.eval_harness.harness --provider modal

# print the suite ids and exit
python -m products.posthog_ai.eval_harness.harness --list
```

| Flag                             | Meaning                                                                          |
| -------------------------------- | -------------------------------------------------------------------------------- |
| `--eval <substr>`                | Only run cases whose name contains the substring.                                |
| `--provider {docker,modal}`      | Where sandboxes run. Default `docker`.                                           |
| `--max-sandboxes N`              | Cap concurrently live sandboxes across all suites.                               |
| `--agent-model <model>`          | Model the sandboxed agent runs against, pinned for stable cross-run comparison.  |
| `--agent-runtime {claude,codex}` | Agent runtime serving the model. Default `claude`.                               |
| `--reasoning-effort <effort>`    | Agent reasoning effort; valid values depend on runtime+model.                    |
| `--keep-sandbox-containers`      | Skip the end-of-run Docker sweep, to inspect a leftover container. Docker only.  |
| `--rebuild-sandbox-image`        | Force a rebuild of the `posthog-sandbox-base` image before the run. Docker only. |
| `--create-db`                    | Rebuild the eval test database instead of reusing it.                            |
| `--case-timeout <seconds>`       | Agent-run budget (minimum 1 second), started after the case's team setup.        |
| `--trials N`                     | Run every case N times (Braintrust trials), for variance on stochastic agents.   |
| `--fail-under <fraction>`        | Exit nonzero when the mean score across all experiments falls below this (0-1).  |
| `--list`                         | Print the discovered suite ids (with their kinds) and exit.                      |

Sandbox-only flags (`--provider`, `--max-sandboxes`, `--agent-runtime`, `--reasoning-effort`, `--keep-sandbox-containers`, `--rebuild-sandbox-image`) are rejected in preflight when no selected suite is sandboxed, instead of being silently ignored.

`EXPORT_EVAL_RESULTS=1` additionally appends one structured JSON summary per experiment to `eval_results.jsonl`.
The full plain-text run transcript is always written without this setting.

### Codex runtime

`--agent-runtime codex` runs the same agent-server with OpenAI's Codex harness instead of Claude, defaulting the model to `gpt-5.5`.
It requires `LLM_GATEWAY_OPENAI_API_KEY` in the environment (checked by preflight), which the harness's LLM gateway uses to proxy the agent's OpenAI calls.
Experiment names don't change with the runtime — each Braintrust experiment records `agent_runtime` and `agent_model` in its metadata instead — so compare cross-run scores within one runtime.

## Providers

Prefer Modal for multi-case sandboxed evals when its prerequisites are available.
Remote sandboxes can run in parallel without consuming local Docker memory, so they usually finish faster.
Use Docker for small smoke tests or when remote access is unavailable.

**docker** (default) runs sandboxes as local containers, so a Docker daemon must be reachable.
Each container defaults to 16 GB, so host RAM is what bounds concurrency: the default cap is 4, and raising `--max-sandboxes` needs a big host.

Every docker run verifies the `posthog-sandbox-base` image is fresh before any case starts: it rebuilds when `@posthog/agent` has published a newer version than the one baked into the image, or when the Dockerfile changed since the image was built.
An unchanged image passes the check in under a second, and even a rebuild is mostly layer-cached — only the npm install layer onward re-runs when the agent version moved.
When npm is unreachable the check warns and reuses the existing image instead of failing the run.
`--rebuild-sandbox-image` forces the rebuild regardless.
(The modal DEBUG image is rebuilt by Modal whenever the Dockerfile or build context changes, but a new `@posthog/agent` publish alone does not invalidate it — a known limitation.)

**modal** runs sandboxes remotely.
Modal's network cannot reach `localhost`, so the harness starts ngrok tunnels itself and points the sandbox at the public URLs.
Eval sandboxes run in the dedicated `posthog-sandbox-evals` Modal app, separate from production and local development sandboxes.
The manual tunnel setup in [`docs/internal/sandboxes-setup-guide.md`](../../../../docs/internal/sandboxes-setup-guide.md) is therefore not needed for evals.
The first modal run pays a one-time remote image build; later runs reuse the cached image until the skills or build context change.

Modal prerequisites, all checked by preflight before anything boots:

- `ngrok` on `PATH`, plus an authtoken (`NGROK_AUTHTOKEN`, or `ngrok config add-authtoken <token>`). Three simultaneous tunnels need a paid ngrok plan; Cloudflare Tunnel is the free alternative.
- Modal credentials: `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`, or a `~/.modal.toml` from `modal token new`.
- `SANDBOX_JWT_PRIVATE_KEY` in the environment. The dev key ships in `.env.example`; the harness auto-loads it from `.env`.

Sandboxes are unbounded by default on modal, meaning every case can hold one at once.
`--max-sandboxes N` is the cost knob.

Each case waits for its workflow to terminate the sandbox, then runs a tag-scoped Modal sweep as a safety net.
When the whole run ends, the harness sweeps the Modal app again for its own leftover sandboxes, so a crashed or interrupted run doesn't leave sandboxes billing until their TTL.
The sweep is scoped to this run's own tasks (matched by the `task_id` sandbox tag), so a second eval run sharing the same Modal app keeps its sandboxes.

## Concurrency

Every selected suite runs concurrently on one event loop, and a global semaphore bounds the number of live sandboxes across all of them.
Selecting more suites therefore increases throughput without increasing peak load.

A separate semaphore covers the full per-case team setup, including the demo-data clone and optional setup hook.
It allows one setup at a time on ordinary local machines and four when either `CODER` or `CI` is set.
These phases can issue large ClickHouse copies or direct inserts, so the independent limit protects ClickHouse from RAM exhaustion even when Modal sandbox capacity is unbounded while letting managed environments prepare cases faster.
When object storage is enabled, setup also validates the master warehouse and clones team-scoped warehouse metadata for each case while reusing the master's immutable CSV files.
When a setup completes, its slot becomes available to the next case while the prepared case runs its agent.

A case holds a sandbox slot only for the window it actually needs one: team setup and the agent run.
Log parsing, Braintrust span building, trace emission, and scoring all happen after the slot is released.
The per-case timeout starts after team setup, so neither sandbox nor setup queueing consumes the agent's budget.

## Suite kinds

Each eval module declares how its suites execute with a module-level `SUITE_KIND` (from `products.posthog_ai.eval_harness.harness.requirements`); a module without one is sandboxed.

| Kind                | Marker                            | What runs per case                      | Infrastructure booted               |
| ------------------- | --------------------------------- | --------------------------------------- | ----------------------------------- |
| sandboxed (default) | none, or `SuiteKind.SANDBOXED`    | the real coding agent in a real sandbox | everything                          |
| one-shot            | `SUITE_KIND = SuiteKind.ONE_SHOT` | one in-process model invocation         | test database, personhog, demo data |

The harness boots the union of what the selected suites require, and a suite that under-declares its kind fails loudly when its runner finds the infrastructure it needed was never booted.

## Adding an eval suite

The `/writing-evals` skill ([.agents/skills/writing-evals](../../../../.agents/skills/writing-evals/SKILL.md)) covers the full authoring workflow — cases, seeders, synthesizers, scorer patterns, and verification.
The short version:

There is no registry. Suites are discovered by convention from two root sets:

- `products/posthog_ai/evals/<domain>/` — the built-in tree, reserved for Max and other agent suites.
- `products/<product>/evals/` — where a product owns its eval suites (plural `evals/`; the singular `products/signals/eval/` is an unrelated pytest tree the harness ignores). Suite id is `<product>/<module>::<fn>`, import path `products.<product>.evals.<module>`.

New product-owned evals belong under `products/<product>/evals/`; that directory needs no pytest-collection exclusion, since pytest's default `python_files` matches `test_*.py` and never collects `eval_*.py` there.

1. Create `products/posthog_ai/evals/<domain>/eval_<name>.py` (or `products/<product>/evals/eval_<name>.py`). The directory becomes the suite's domain.
2. Write one or more coroutines named `eval_*` taking a single `ctx: EvalContext`.
3. Build a list of `SandboxedEvalCase` and hand it to `SandboxedPrivateEval` or `SandboxedPublicEval` along with your scorers and `ctx=ctx`.

```python
from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext


async def eval_my_thing(ctx: EvalContext) -> None:
    await SandboxedPrivateEval(
        experiment_name="sandboxed-my-thing-cli",
        cases=[SandboxedEvalCase(name="my_case", prompt="...")],
        scorers=[],
        ctx=ctx,
    )
```

The harness automatically adds the `ExitCodeZero` scorer to every sandboxed experiment.
Do not add it to a suite's `scorers` list; the harness rejects duplicates.

For a one-shot suite, declare the kind, build `BaseEvalCase`s, and pass a task function to `OneShotPrivateEval` / `OneShotPublicEval` — the task runs once per case under the global one-shot limiter and returns the scorer `output` dict directly:

```python
from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPrivateEval

SUITE_KIND = SuiteKind.ONE_SHOT


async def eval_my_generation(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        return {"answer": ...}  # one model invocation; JSON-serializable

    await OneShotPrivateEval(
        experiment_name="my-generation",
        cases=[BaseEvalCase(name="my_case", prompt="...")],
        scorers=[...],
        task=task,
        ctx=ctx,
    )
```

Bundle related cases into one suite function rather than splitting them across many.
One suite is one Braintrust experiment, which is what makes cross-case comparison and `--eval` filtering useful.

`experiment_name` is the Braintrust experiment key, so changing it starts a fresh history.
Existing suites end in `-cli` because the MCP server serves the `cli` surface; that suffix is kept so history lines up with earlier runs.

Confirm discovery picked your suite up:

```bash
python -m products.posthog_ai.eval_harness.harness --list | grep my_thing
```

## Output

Progress lines use stable labels as cases and suites start or finish: `SUITE START`, `EXPERIMENT START`, `CASE DONE`, `EXPERIMENT DONE`, and `SUITE DONE`.
Only the overall run uses `PASS` or `FAIL`, so a suite with a low behavioral score still reads as completed rather than passed.
The final summary gives labeled suite and case totals, the score gate, total duration, and one block per experiment with scorer averages, PostHog and Braintrust URLs, and the agent-log directory.
A crashed suite is labeled `CRASH`, includes its traceback in the summary, and makes the run exit nonzero without taking down the other suites.

Every real eval invocation mirrors its complete stdout and stderr to:

```text
products/posthog_ai/eval_harness/logs/harness/<timestamp>_<id>.log
```

The line before the path identifies it as the full stdout/stderr run transcript.
The final terminal line is the unlabeled absolute path, with no output after it, so a person or agent can reliably open it.
The transcript itself ends with the same path, and `logs/harness/latest.log` points to the newest transcript.
Suite listing (`--list`) and argument errors do not create transcripts.

Raw per-case agent logs land on local disk (`<case>.jsonl`, `<case>.artifacts.json`, `<case>.summary.txt`), which is usually the fastest way to see what the agent actually did.

`SandboxedPrivateEval` runs with `no_send_logs`, so its summary has no Braintrust URL; the local logs are the record.
