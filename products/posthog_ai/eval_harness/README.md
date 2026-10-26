# Sandboxed agent evals

These evals run the real coding agent inside a real sandbox against a seeded Hedgebox project, then score what it did.
Each eval case gets its own isolated org/team/user, so cases never see each other's state.

The harness builds product skills from the current checkout and uses native bundled skills by default.
`--skill-delivery exec` instead packages those skills for MCP distribution, enables the exec skill prompt, and removes native skills from every sandbox so the two paths cannot satisfy the same case.

This is the eval harness for PostHog AI 2.0. It does **not** run under pytest.
It runs on a standalone harness that boots the shared infrastructure once (test database, Django live server, AI gateway, MCP server, Temporal) and then runs every selected suite concurrently.
See [`harness/README.md`](harness/README.md) for how that works internally.

The harness also hosts non-sandboxed suite kinds — see [Suite kinds](#suite-kinds).
A run boots only the infrastructure its selected suites need, so a one-shot-only run starts no sandbox provider, Temporal, live server, AI gateway, or MCP server.

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
Which variables are required depends on the selected suites' reporting settings and kinds: the Braintrust engine requires `BRAINTRUST_API_KEY` only if at least one selected suite sends logs to Braintrust. A run consisting entirely of suites declaring `NO_SEND_LOGS = True` does not require that reporting credential. Sandboxed suites require `SANDBOX_JWT_PRIVATE_KEY` and `LLM_GATEWAY_ANTHROPIC_API_KEY`, and need a [`PostHog/ai-gateway`](https://github.com/PostHog/ai-gateway) clone plus `go` on `PATH` (see [AI gateway](#ai-gateway)); one-shot suites require `LLM_GATEWAY_ANTHROPIC_API_KEY` (used directly, no gateway).
Scorers still need credentials for their model provider. A scorer configured to use Braintrust's model proxy needs its proxy credential independently of result reporting.

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

| Flag                              | Meaning                                                                                                  |
| --------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `--eval <substr>`                 | Only run cases whose name contains the substring.                                                        |
| `--provider {docker,modal}`       | Where sandboxes run. Default `docker`.                                                                   |
| `--max-sandboxes N`               | Cap concurrently live sandboxes across all suites.                                                       |
| `--agent-model <model>`           | Model the sandboxed agent runs against, pinned for stable cross-run comparison.                          |
| `--agent-runtime {claude,codex}`  | Agent runtime serving the model. Default `claude`.                                                       |
| `--skill-delivery {bundled,exec}` | Skill delivery path. Default `bundled`; `exec` removes native sandbox skills.                            |
| `--reasoning-effort <effort>`     | Agent reasoning effort; valid values depend on runtime+model.                                            |
| `--keep-sandbox-containers`       | Skip the end-of-run Docker sweep, to inspect a leftover container. Docker only.                          |
| `--rebuild-sandbox-image`         | Force a rebuild of the `posthog-sandbox-base` image before the run. Docker only.                         |
| `--create-db`                     | Rebuild the eval test database instead of reusing it.                                                    |
| `--case-timeout <seconds>`        | Agent-run budget (minimum 1 second), started after the case's team setup.                                |
| `--verbose`                       | Show detailed logs and tracebacks in the console. The transcript always keeps the detailed logs.         |
| `--tui`                           | Force the interactive view using the session's terminal, including when standard streams are redirected. |
| `--no-tui`                        | Use plain text output, including in an interactive terminal.                                             |
| `--trials N`                      | Run every case N times (Braintrust trials), for variance on stochastic agents.                           |
| `--infra-retries N`               | Retry temporary case setup failures and service readiness timeouts N times. Default 2; use 0 to disable. |
| `--fail-under <fraction>`         | Exit nonzero when the mean score across all experiments falls below this (0-1).                          |
| `--list`                          | Print the discovered suite ids (with their kinds) and exit.                                              |

Sandbox-only flags (`--provider`, `--max-sandboxes`, `--agent-runtime`, `--skill-delivery`, `--reasoning-effort`, `--keep-sandbox-containers`, `--rebuild-sandbox-image`) are rejected in preflight when no selected suite is sandboxed, instead of being silently ignored.

The run exits with status 1 if a suite crashes or a case has an infrastructure error, even without `--fail-under`.
Infrastructure errors remain separate from score averages.
Case timeouts and low scores affect the exit status only through `--fail-under`.

Temporary case setup failures and support-service readiness timeouts receive two retries by default.
The default delays are 1 second and 2 seconds.
Setup retries cover connection failures, temporary PostgreSQL failures, ClickHouse overload, query timeouts or memory limits, and object-storage server errors.
Known PostgreSQL transport failures can retry without a SQLSTATE.
Failed setup steps close unusable Django connections in the same worker thread before a retry.
Each case setup retry creates fresh test data before the agent starts.
The runner releases the team setup permit during the delay and stops the previous service process before a readiness retry.
`CASE RETRY` and `STARTUP RETRY` messages show the next attempt and delay.
The final summary counts case setup retries separately from case errors.
Case metadata records `setup_attempts` and `setup_retry_errors`.
The runner retries neither agent work nor low scores, case timeouts, authentication errors, setup code errors, or services that exit during startup.
Existing sandbox-creation and storage-read retries still apply.

The case budget starts after team setup. Polling uses one monotonic deadline across all turns.
The harness reserves up to 120 seconds, capped at one quarter of the case budget, for log recovery and cleanup.
The outer case timeout remains the final guard. Slow setup or storage reads cannot give a follow-up a fresh case budget.
Poll timeouts keep their diagnostic stage and log counts in case metadata and the local artifacts file. They remain scored timeouts.
A timeout summary contains the failure reason. Its raw log file can be empty; the full run transcript retains streamed agent output.

`EXPORT_EVAL_RESULTS=1` additionally appends one structured JSON summary per experiment to `eval_results.jsonl`.
The full plain-text run transcript is always written without this setting.
Interactive terminals show a live view by default. CI and redirected standard input or output use plain text.
Plain text output shows runner progress, summaries, and short error messages.
Dependency warnings, SDK progress bars, and direct setup prints stay in the transcript.
`--verbose` also shows Python warnings, SDK output, and detailed logs in the console.
Native subprocess output always goes to the transcript.

### AI gateway

Sandboxed agents call their model through the Go [`PostHog/ai-gateway`](https://github.com/PostHog/ai-gateway), as PostHog AI runs do in production.
The harness builds and starts it from a local clone at `~/Development/ai-gateway`, the same path `bin/start-ai-gateway` uses. Set `AI_GATEWAY_REPO` to use a clone at a different path.

```bash
git clone git@github.com:PostHog/ai-gateway.git ~/Development/ai-gateway
```

The gateway runs on `:18080` with its own Postgres database and Valkey DB index in the clone's compose containers, so it does not touch a dev-stack gateway's ledger or blobs.
It uses `LLM_GATEWAY_ANTHROPIC_API_KEY` and `LLM_GATEWAY_OPENAI_API_KEY` as its provider keys.
The harness adds test credits to the master demo team in this separate ledger. Scoped tokens require a positive balance and cannot use an overspend allowance.
Each run gets a capped `phe_` token minted with a key on that team, so spend is per run and never reaches a real wallet. The harness refreshes the mint key during long runs. It retries temporary database or Redis errors until the credential expires. Retry delays increase to at most one minute.
If token minting fails, the fallback URL stays on the eval gateway, which rejects requests without a run token.

### Interactive view

The view is `phrocs evals`, the same Bubble Tea program that renders `hogli start`.
It runs in its own process, so a busy eval run does not delay key presses or redraws.
The harness builds the in-repo phrocs (`tools/phrocs/dist/phrocs`) when Go is available, otherwise it uses `phrocs` on `PATH`.
If phrocs is missing or too old to have the `evals` command, the run continues with plain text output.

The sidebar shows the run and one row per trial, grouped by experiment, with status and elapsed time.
A failed trial shows its full error and traceback. Select **Run** for setup status, trial counts, and warnings. Press `l` to switch to the full run transcript.
During agent execution, use this transcript for live logs. Per-trial log files become available after execution.
Click a row or use the mouse wheel over the sidebar to change the selection. The wheel over the output pane scrolls it.
Drag over the output pane to select text. The view copies the selection when you release the button, through OSC 52 and `pbcopy` on macOS.

| Key                      | Action                                                                               |
| ------------------------ | ------------------------------------------------------------------------------------ |
| Up/Down, `j`/`k`         | Select a trial or the run, or scroll when the output pane has focus                  |
| Tab, Enter               | Move focus between the sidebar and the output pane                                   |
| `l`                      | Switch between the summary and logs                                                  |
| `/`, Up/Down, Escape     | Search the output, move between matches, or clear the search                         |
| PgUp/PgDn, Home          | Scroll the output                                                                    |
| End                      | Jump to the end and follow new output                                                |
| `q`, then `y`            | Cancel a running eval and wait for cleanup; `n` continues the run                    |
| Ctrl-C                   | Cancel once and wait for cleanup                                                     |
| `q` after completion     | Close the view                                                                       |
| Mouse drag in the output | Select text; releasing the button copies it to the clipboard                         |
| `c`, then `c` twice      | Select lines with Up/Down and copy them; the mouse can also drag-select in this mode |
| `?`                      | Show all keys                                                                        |

The final results stay visible until you close the view. The terminal then prints the final summary and transcript path.
Use `--no-tui` for the existing text output. `--verbose` adds detailed messages to the view or text output.
`--tui` overrides automatic detection, including `TERM=dumb` and CI. It uses `/dev/tty` when a launcher redirects standard input or output.
Redirecting stderr alone does not disable the view. A session without an attached terminal still requires `--no-tui`.
`hogli evals` opens the view by default in a terminal, even though its secrets wrapper pipes stdout. Redirect the output of `hogli evals` to get text output.
With `--tui`, setup starts only after the first screen is drawn. A startup failure stops the command and reports its cause.
If the view exits during a run, the runner stops through its cleanup path and saves the view error in the transcript.
The view does not change scores, retries, timeouts, or sandbox cleanup. Its screen controls are not written to the transcript.

### Comparing skill delivery

MCP instructions are configured once for the whole harness process, so bundled and exec skill delivery must run separately.
Use the same suite, model, runtime, provider, case filter, and trial count in both commands:

```bash
hogli evals eval_skill_distribution --skill-delivery bundled --agent-runtime claude --agent-model claude-opus-4-8 --trials 3
hogli evals eval_skill_distribution --skill-delivery exec --agent-runtime claude --agent-model claude-opus-4-8 --trials 3
```

Both runs use the same prompts and Braintrust history key.
The experiment metadata records `skill_delivery`; compare the shared `expected_skill_loaded` and `skill_loaded_before_tool` scores rather than the aggregate mean, because the exec arm also reports search and discovery diagnostics.

### Codex runtime

`--agent-runtime codex` runs the same agent-server with OpenAI's Codex harness instead of Claude, defaulting the model to `gpt-6.1-sol`.
It requires `LLM_GATEWAY_OPENAI_API_KEY` in the environment (checked by preflight), which the harness's AI gateway uses to proxy the agent's OpenAI calls.
Experiment names don't change with the runtime or skill delivery. Each Braintrust experiment and every PostHog event records `agent_model`, `trials`, `git_sha` and `git_dirty`. Sandboxed runs add `agent_runtime`, `skill_delivery` and `reasoning_effort`. Use these fields to separate runs. A comparison across runtimes measures the model and runtime together.

### Claude and Codex smoke comparison

Run both default models and print one comparison with `--compare`:

```bash
hogli evals cli_mcp/eval_skill_distribution::eval_skill_distribution \
  --eval historical_traffic_share_by_type \
  --provider modal --skill-delivery exec \
  --trials 3 --max-sandboxes 2 --compare
```

Both configurations are checked before either agent run starts. The models run in order, in separate processes,
with the same suite selectors, case filter, provider, skill delivery, trial count, timeout, and concurrency.
Comparisons use plain text output so each model can finish without waiting for the interactive view to close.
Ctrl-C stops the comparison after the current child finishes cleanup.

Use repeated `--compare-model claude:MODEL` and `--compare-model codex:MODEL` options to replace the default pair.
At least two distinct runtime/model pairs and one suite selector are required. Only sandboxed suites are supported;
one-shot suites select their models internally. Do not combine comparison options with `--agent-model` or `--agent-runtime`.

The command saves `comparison.json`, `comparison.txt`, and each child's run report under `logs/comparisons/<run>/`.
Use `--comparison-dir PATH` to choose a new directory. Existing directories are rejected to protect previous results.
Each model retains its own full transcript, and the comparison has a combined transcript whose path prints last.
Reports retain completed models if a later model fails or the comparison is interrupted.

The table shows named scorer means with scored-trial counts, completed execution coverage, errors, timeouts, and wall time.
Missing and skipped scores show `n/a`; a real zero shows `0.0%`. Costs show `unavailable` because these results do not contain cost data.
Case-set, scorer-set, or checkout differences produce a warning and a nonzero exit status.
Errors, timeouts, incomplete results, and failed score gates also make the comparison exit nonzero.
The comparison measures model plus runtime. A small smoke case is not a model ranking.

Use `--check` without comparison options to validate a single run without starting services or agents.
Use `--results-file PATH` on a single run to save its structured scores, coverage, settings, and log locations.

The manual command pair remains available:

Start with one fixed MCP case. It checks skill discovery and tool use for a historical traffic query.
Both commands below use the same case, provider, skill delivery, concurrency, and scorers.
Run them in order from the same checkout. Separate harness processes share service ports, so do not run them together.

Prepare the normal [provider prerequisites](#providers) and both model credentials before starting.
Claude requires `LLM_GATEWAY_ANTHROPIC_API_KEY`; Codex also requires `LLM_GATEWAY_OPENAI_API_KEY`.

```bash
eval_comparison_args=(
    cli_mcp/eval_skill_distribution::eval_skill_distribution
    --eval historical_traffic_share_by_type
    --provider modal
    --max-sandboxes 1
    --skill-delivery exec
    --trials 1
)
EXPORT_EVAL_RESULTS=1 hogli evals "${eval_comparison_args[@]}" --agent-runtime claude --agent-model claude-opus-5-5
EXPORT_EVAL_RESULTS=1 hogli evals "${eval_comparison_args[@]}" --agent-runtime codex --agent-model gpt-6.1-sol
```

Compare the named scorer results, completed cases, timeouts, infrastructure errors, and total duration in both final summaries.
Keep both transcript paths and both agent-log directories. Each directory contains `case_results.jsonl` with scores and trial IDs.
Check the recorded `git_sha` and `git_dirty` values before comparing runs.
Treat missing or errored trials as incomplete coverage, rather than a model score.
This is a smoke comparison, not a broad model ranking. Set `--trials 3` in the shared arguments to check repeatability after the first pair completes.
Remove `--eval historical_traffic_share_by_type` to compare the full skill-distribution suite.

## Providers

Prefer Modal for multi-case sandboxed evals when its prerequisites are available.
Remote sandboxes can run in parallel without consuming local Docker memory, so they usually finish faster.
Use Docker for small smoke tests or when remote access is unavailable.

**docker** (default) runs sandboxes as local containers, so a Docker daemon must be reachable.
Each container defaults to 16 GB, so host RAM is what bounds concurrency: the default cap is 4, and raising `--max-sandboxes` needs a big host.
A case running notebook python or duckdb cells holds a second container on top of that (see [Notebook kernel sandboxes](#notebook-kernel-sandboxes)), which the sandbox cap does not count.

Every docker run verifies the `posthog-sandbox-base` image is fresh before any case starts: it rebuilds when the `ARG AGENT_VERSION` pin in the Dockerfile differs from the version baked into the image, or when the Dockerfile changed since the image was built.
An unchanged image passes the check in under a second, and even a rebuild is mostly layer-cached — only the npm install layer onward re-runs when the agent version moved.
`--rebuild-sandbox-image` forces the rebuild regardless.
(Modal rebuilds the DEBUG image whenever the Dockerfile or build context changes, so a pin bump reaches it the same way.)

**modal** runs sandboxes remotely.
Modal's network cannot reach `localhost`, so the harness exposes the host services via Tailscale Funnel itself and points the sandbox at the public URLs.
A new Funnel takes up to a few minutes before all of its public relays serve it, so Modal setup waits for them before the first case starts.
Eval sandboxes run in the dedicated `posthog-sandbox-evals` Modal app, separate from production and local development sandboxes.
The manual tunnel setup in [`docs/internal/sandboxes-setup-guide.md`](../../../../docs/internal/sandboxes-setup-guide.md) is therefore not needed for evals.
The first modal run pays a one-time remote image build; later runs reuse the cached image until the skills or build context change.

Modal prerequisites, all checked by preflight before anything boots:

- `tailscale` on `PATH`, with tailscaled running and this node logged in (`tailscale up`). Funnel must be enabled for the tailnet and this node in the admin console's ACLs, with HTTPS certificates enabled. The harness serves Django, the AI gateway, and MCP on Funnel's three public ports (443, 8443, 10000).
- Modal credentials: `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`, or a `~/.modal.toml` from `modal token new`.
- `SANDBOX_JWT_PRIVATE_KEY` in the environment. The dev key ships in `.env.example`; the harness auto-loads it from `.env`.

Sandboxes are unbounded by default on modal, meaning every case can hold one at once.
`--max-sandboxes N` is the cost knob.

Each case waits for its workflow to terminate the sandbox, then runs a tag-scoped Modal sweep as a safety net.
When the whole run ends, the harness sweeps the Modal app again for its own leftover sandboxes, so a crashed or interrupted run doesn't leave sandboxes billing until their TTL.
The sweep is scoped to this run's own tasks (matched by the `task_id` sandbox tag), so a second eval run sharing the same Modal app keeps its sandboxes.

## Notebook kernel sandboxes

A notebook SQL cell whose refs are all HogQL runs on the direct lane — the async query manager, no sandbox — and needs nothing beyond the live server.
A python or duckdb cell instead dispatches the notebook Temporal workflow, which provisions a **second** sandbox for the case: the notebook kernel, ~2 GB alongside the agent's 16 GB.

The harness supports that lane on **docker only**.
The notebook kernel resolves its backend straight from `SANDBOX_PROVIDER`, and the modal provider sets that to `MODAL_EVALS`, which is not one of `KernelRuntime.Backend`'s values — the port map and liveness checks both miss, and the kernel never comes up.
Run suites with python or duckdb cells as `--provider docker`; SQL-only suites are unaffected and run anywhere.

Three things make the lane work, all automatic:

- The eval Temporal worker registers the notebook workflows next to the tasks ones, and `GENERAL_PURPOSE_TASK_QUEUE` (where notebook runs dispatch) points at the same per-process queue, so one worker serves both.
- `SANDBOX_API_URL` already points the sandbox at the Django live server, which is where the kernel posts its result callback and reads the data plane.
- The docker provider builds the notebook image during startup. Left to first use it would build inside a Temporal activity with a five-minute budget, and a cold build overruns it.

Kernel sandboxes are reclaimed by the harness, not by a TTL — the docker backend ignores `SandboxConfig.ttl_seconds`.
Each case destroys its own before releasing its sandbox slot, and the run sweeps the eval database for stragglers at both ends.
`--keep-sandbox-containers` preserves kernel containers the same way it preserves agent ones.

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

In plain text output and the transcript, progress lines use stable labels as cases and suites start or finish: `SUITE START`, `EXPERIMENT START`, `CASE START`, `CASE PHASE`, `CASE READY`, `CASE DONE`, `EXPERIMENT DONE`, and `SUITE DONE`.
Only the overall run uses `PASS` or `FAIL`, so a suite with a low behavioral score still reads as completed rather than passed.
The console shows case starts and phase changes for each trial.
A status line every 30 seconds shows execution totals, phase counts, elapsed time, and the oldest active trial.
`CASE READY` means execution completed; scoring and result collection are still pending.
`CASE DONE` and `EXPERIMENT DONE` mean the scores are ready.
The `scoring` phase includes time waiting for all results in that experiment, so it is not an isolated scorer duration.
Use `--verbose` to show detailed service and agent logs in the console. The transcript retains these logs in both modes.
Warnings and errors use short console messages, including the exception type and message when available.
Open the transcript for full tracebacks.

The final summary gives labeled suite and case totals, the score gate, total duration, and one block per experiment with scorer averages, PostHog and Braintrust URLs, and the agent-log directory.
Each scorer line shows its score with a 95% confidence interval clustered by case. With `--trials N` a second line adds pass^N (every trial passed), pass@N (any trial passed) and the number of flaky cases, counting only cases scored on all N trials, so a noisy suite is distinguishable from a real score change.
A crashed suite is labeled `CRASH` and makes the run exit nonzero without taking down the other suites.
Its full traceback stays in the transcript. `--verbose` also shows the traceback in the final summary.

Every real eval invocation mirrors its complete stdout and stderr to:

```text
products/posthog_ai/eval_harness/logs/harness/<timestamp>_<id>.log
```

The line before the path identifies it as the full stdout/stderr run transcript.
The final terminal line is the unlabeled absolute path, with no output after it, so a person or agent can reliably open it.
The transcript itself ends with the same path, and `logs/harness/latest.log` points to the newest transcript.
Suite listing (`--list`) and argument errors do not create transcripts.

Each trial writes separate local files: `<case>.trial-<id>.jsonl`, `<case>.trial-<id>.artifacts.json`, and `<case>.trial-<id>.summary.txt`.
The harness shortens long case names in filenames to stay within 255 bytes. It keeps the complete trial ID and file extension.
The summary includes the trial ID, the agent trace ID when available, phase durations in seconds, and the scores for that trial.
Case names and `--eval` filters stay the same.

`SandboxedPublicEval` sets `no_send_logs=False` and reports results to Braintrust, plus PostHog when the suite has offline publishing configured.
`SandboxedPrivateEval` sets `no_send_logs=True` and uploads results to neither service by default; local logs are still written.
Both sandboxed and one-shot suites can set `send_to_posthog=True` with `offline_suite` to publish only to PostHog while Braintrust uploads remain disabled, or `send_to_posthog=False` to disable PostHog uploads independently.
The 11 experiment-skill suites use this PostHog-only mode.
PostHog result uploads default to following `no_send_logs`, independently of `OPT_OUT_CAPTURE`, which still applies to ordinary SDK and trace clients.
See [evaluation result reporting](../../../docs/internal/ai-offline-evaluation-reporting.md) for capture settings and scope.

### SQL offline experiment pilot

The `sql/eval_sql::eval_sql` suite can also send its seven scorer results to PostHog's offline experiment API.
It publishes the same completed case results through the Python SDK and keeps sending to Braintrust.
PostHog AI and Slack app public suites also opt into offline publishing with their own tagged scorer versions.
Agent and judge trace capture remains available. `no_send_logs=True` suppresses offline result uploads unless `send_to_posthog=True` is explicitly set.

Set `POSTHOG_OFFLINE_EVAL_API_KEY` to a personal key with `offline_evaluation_ingestion:write`, `evaluation:write`, and access to project `2` to upload and tag results. An ingestion-only personal or project secret key can upload results, but tagging will warn and leave the run untagged.
The [SQL suite definition](../evals/sql/eval_sql.py) pins that project ID and all seven immutable scorer version UUIDs in code.
`POSTHOG_OFFLINE_EVAL_HOST` defaults to `https://us.posthog.com`.
For development, use `http://localhost:8010` with a local API key and set `POSTHOG_OFFLINE_EVAL_LOCAL_CONFIG`
to a gitignored JSON file containing the local project ID and scorer-version mappings.
See [local upload setup](../../../docs/internal/ai-offline-evaluation-reporting.md#testing-uploads-against-local-posthog).
The [suite configuration](../../../docs/internal/ai-offline-evaluation-reporting.md#configured-offline-experiment-suites) lists the metrics and explains local and CI key configuration.
Delivery runs in a bounded background queue after local results are saved. Prepared uploads stay in memory, with up to two uploads running concurrently, at most 32 queued or active uploads, and a 60-second deadline per active upload.
A completed upload records its results link before tagging begins. Tagging has a separate five-second deadline; failures, timeouts, and shutdown interruptions only warn and preserve the successful upload status.
Unfinished uploads pause before infrastructure teardown. After teardown, the harness retries the same prepared objects and identities with fresh deadlines, waiting up to the full 60-second upload deadline for delivery to finish.
Requests use a 5-second timeout and up to two retries within that overall deadline. Terminal API failures trigger a best-effort attempt to mark the experiment failed, limited to 5 seconds; pauses and interruptions leave it resumable.
Both sandboxed and one-shot suites can opt in through `offline_suite`. Rich scorer recording runs only when offline publishing is configured and uploads are allowed.
The [reporting guide](../../../docs/internal/ai-offline-evaluation-reporting.md#enrolling-other-suites-and-richer-results) covers rich scorer outcomes, external dataset references, version fields, and suite configuration. Hosted datasets are not supported by the harness publisher.

```bash
hogli evals sql/eval_sql::eval_sql
```

With no API key, the SQL run reports that offline uploads are disabled.
Invalid configuration and upload failures produce warnings while Braintrust and local reporting continue.
Successful uploads use separate items for each case and trial; skipped scores and execution errors remain distinct from scores of zero.
Raw agent logs stay in the existing local and Braintrust outputs. The SDK validates payloads; invalid or oversized optional fields are omitted as a whole, with their names recorded in metadata.

Failed or interrupted uploads and uploads rejected by a full queue are not saved for later retry.
To try publishing again, correct the configuration or connectivity problem and rerun the suite.
Existing local logs, enabled case exports, and Braintrust results remain available; upload failures do not change the score gate.
