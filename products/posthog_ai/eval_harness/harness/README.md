# The sandboxed eval harness

This package is the runner for `products/posthog_ai/eval_harness/`.
For how to _use_ it, read [`../README.md`](../README.md).
For the rules to preserve when _changing_ it, read [`AGENTS.md`](AGENTS.md).
This file explains how it fits together.

## Why it exists

The sandboxed evals need heavy shared infrastructure: a committed test database, an in-process Django server the sandbox can call back into, the Go AI gateway, an MCP server, and a Temporal server plus worker.
Under pytest that infrastructure lived in session fixtures, and suites ran strictly one at a time, with Braintrust parallelizing only _within_ a suite.
Wall-clock was dominated by suites queueing behind each other while sandbox capacity sat idle.

The harness boots the same infrastructure once, then runs every suite concurrently on a single event loop and bounds sandbox and team-setup load with shared semaphores.
Braintrust remains the eval engine and reporting backend; it just no longer controls scheduling.
The `EvalAsync` call itself lives behind an `EvalEngine` seam (`../engines/`): `_BaseEvalRun.run()` hands a neutral `ExperimentSpec` to the engine resolved by `engines/registry.resolve_engine()` (shared via `EvalContext.engine`) and gets back a neutral `ExperimentResult` (`engines/types.py`), so a future PostHog-native engine can slot in behind the same interface — implementing the `EvalEngine` protocol and passing the conformance suite — without touching the run base or any suite.

Not every suite is sandboxed anymore: each suite declares a `SUITE_KIND` (`requirements.py`), the kind maps to a set of `Infra` requirements, and the harness boots only the union of what the selected suites need.
A run of one-shot suites never pays for — or fails preflight on — the sandbox provider, Temporal, the live server, the AI gateway, or the MCP server.

## Modules

| Module             | Role                                                                                                                                       |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `__main__.py`      | Entry point. Parses args, starts the transcript, configures Django, then hands off to `lifecycle`.                                         |
| `cli.py`           | `HarnessOptions` and the argparse builder. Resolves per-provider defaults.                                                                 |
| `env_preflight.py` | Loads the repo-root `.env` (stdlib parser, shell wins) and validates per-kind env vars via pydantic models.                                |
| `ports.py`         | The seven port constants. Deliberately free of Django imports.                                                                             |
| `providers.py`     | `SandboxProviderStrategy` and its docker/modal implementations: preflight, settings overrides, sandbox TTL, cleanup.                       |
| `tunnels.py`       | `TailscaleFunnel`. Modal only: enables Tailscale Funnel on the host services, waits for the public relays, and resolves the URLs.          |
| `requirements.py`  | `SuiteKind`, `Infra`, and the kind → infrastructure mapping (with implication closure).                                                    |
| `django_env.py`    | `setup_django()`, the `NullDbBlocker` shim, and `EvalDatabase` (test database lifecycle).                                                  |
| `live_server.py`   | `EvalLiveServer`, a session-lifetime Uvicorn server for PostHog's full ASGI application.                                                   |
| `services.py`      | Starts the AI gateway, MCP server, skill archive server, and personhog subprocesses; provisions the gateway mint key; builds local skills. |
| `temporal_env.py`  | Local Temporal dev server, stale-workflow cleanup, and the worker thread.                                                                  |
| `demo_data.py`     | `SandboxedDemoData`: seeds the master Hedgebox team once, then mints an isolated team per case.                                            |
| `discovery.py`     | Walks the tree for `eval_*.py` and collects `eval_*` coroutines into `EvalSuite` objects.                                                  |
| `context.py`       | `EvalContext`, the single object every suite receives.                                                                                     |
| `reporting.py`     | `ProgressReporter` and the final summary table. The quiet Braintrust reporter lives with the engine (`../engines/braintrust.py`).          |
| `transcript.py`    | Mirrors stdout and stderr to one run log, then publishes its absolute path as the final line.                                              |
| `dashboard.py`     | Starts the `phrocs evals` view process and streams run progress to it over a socket pair.                                                  |
| `progress.py`      | Immutable trial progress shared by the reporter and interactive view.                                                                      |
| `terminal.py`      | Opens terminal streams without sharing the descriptors used by transcript capture.                                                         |
| `lifecycle.py`     | `SandboxedEvalHarness`: orchestrates bootstrap, the run, and teardown.                                                                     |

## Boot sequence

Discovery happens first, before anything is provisioned, so a typo'd selector costs a module import rather than a database build.
Every step below is gated on the selected suites' infrastructure union — a step whose `Infra` member no run requires is skipped, and skipped steps register no teardown.
The sequence as written is the sandboxed (full) path; a one-shot-only run performs just steps 1–3 and 6.

The bootstrap is deliberately synchronous and runs before any event loop exists, because it is ORM-heavy and Django's async-safety guard rejects sync ORM calls from an async context:

1. `__main__` creates the run transcript, then loads the repo-root `.env` (never overriding what the shell — or hogli's own env loading, under `hogli evals` — already exported), then `setup_django()` sets `DEBUG` / `TEST` / `IN_EVAL_TESTING`, forces `SELF_CAPTURE=0`, and runs `django.setup()` and `setup_test_environment()`. Eval telemetry still uses the explicit regional client configured by the harness.
   The env preflight (required variables, one-line fix per missing one) and provider preflight then run, followed by the personhog binary build (`cargo build`, incremental after the first run) and the AI gateway build (`go build` in the `PostHog/ai-gateway` clone) — a missing key or toolchain fails here, before any database work.
2. `EvalDatabase.setup()` creates the `default` test database and drives PostHog's own eval database setup (persons database, ClickHouse).
3. `personhog-replica` (`:15051`) and `personhog-router` (`:15052`) start against the test persons database — before anything can query, so a dead router never poisons the negative group-types cache.
4. `EvalLiveServer` serves PostHog's ASGI application on `0.0.0.0:18000`, including the sandbox event-ingest route.
5. The Go AI gateway (`:18080`) starts in resolver mode, on the gateway compose Postgres (database `ai_gateway_evals`) and Valkey (DB 5).
6. The master Hedgebox team is seeded. This happens before the skill build, because HogQL examples in skill templates render against a Team, and a fresh test database has none until this step.
7. Local skills are built. A failed build stops the run instead of reusing an older `dist/skills`. In bundled mode, the MCP server (`:18787`) starts with exec skill distribution forced off. In exec mode, the skills are packaged, the local archive server (`:18788`) starts, and MCP receives its content-addressed URL with distribution forced on.
8. Docker only: the `posthog-sandbox-base` image freshness check runs (rebuilding when the Dockerfile or its agent pin changed). Modal only: Tailscale Funnel comes up, exposing the callback services publicly. Setup then waits until every public Funnel relay serves every service, because the relays start serving at different times and can take minutes.
9. Bundled mode bind-mounts the built skills on Docker and bakes them into the Modal image. Exec mode suppresses those skills and clears native skill directories before every case; `disable_bundled_skills=True` remains available as a per-case override in other modes.
10. The master team gets the AI gateway mint key: a `phs_` key, gateway admission, and test credits in the separate eval ledger. One model listing and one token mint check that path before any case starts. The harness refreshes the same mint credential before its cache TTL expires during the run.

Gateway cache writes stay disabled until the gateway starts. A one-shot run leaves them disabled.

The async phase then starts the Temporal dev server on the main loop, applies the provider's settings overrides, terminates stale workflows, starts the Temporal worker on its own thread and loop, and fans the suites out with `asyncio.gather`.

Teardown unwinds an `ExitStack` and an `AsyncExitStack` in reverse.
`atexit` hooks and the subprocess manager's signal handlers cover the Ctrl-C path, where neither stack unwinds.
The final summary renders after teardown, logging is flushed, and the transcript path is emitted last.

## Output model

`--compare` runs the selected sandboxed suites through Claude and Codex in separate, sequential child processes.
The comparison checks every configuration first with `--check`, then forwards child output into its combined transcript.
`--results-file` writes a validated run report using the reporter's existing scores, status counts, and case selection.
The comparison retains these reports after each model and checks that case and scorer selections match.
No prompts, model answers, or credentials are included in the comparison report.

The reporter emits plain-text records with stable labels so terminals and agents can scan the same output.
`START` marks work entering flight, `DONE` marks successful completion, and `TIMEOUT`, `ERROR`, or `CRASH` name exceptional outcomes.
Only the final overall run status uses `PASS` or `FAIL`.
`CASE START` and `CASE PHASE` identify each trial. `CASE READY` marks completed execution with scoring still pending.
The reporter prints phase counts and the oldest active trial every 30 seconds while suites run.
The `scoring` duration includes waiting for the experiment results. It does not measure scorer execution alone.
Public runs update Braintrust trial metadata after scoring so it contains the final phase durations.
Scorer exceptions produce case errors in the console and final summary.
The reporter writes output in worker threads so slow output does not stop the event loop.
Terminal writes do not hold the transcript file lock, so progress output cannot block logging through that lock.
The runner starts workflow cleanup before progress reporting.
Cancellation during progress reporting does not stop workflow cleanup.
The sandbox window always reclaims notebook kernels after the agent run, without another progress report.
Interactive terminals use the dashboard by default. CI, pipes, and `--no-tui` use concise text output.
`--tui` overrides CI and `TERM=dumb` detection and opens `/dev/tty` when standard input or output is redirected.
Redirected stderr does not disable automatic detection. Sessions without a controlling terminal use text output.
`hogli evals` runs through the secrets wrapper (`op run`), which pipes stdout. hogli records whether its own stdout was a terminal in `HOGLI_STDOUT_TTY`, and detection uses that record when stdout is a pipe.
`--verbose` shows detailed logging and tracebacks.
Both modes retain detailed logs in the transcript, including routine service stderr without a warning label.

The reporter publishes immutable trial updates to the dashboard; the view does not parse log lines to infer case state.
The view is a separate `phrocs evals` process (`tools/phrocs/internal/tui/evals.go`). It owns the terminal, so the harness's GIL never delays input or rendering.
The harness passes one end of a socket pair with `--fd`. It writes one JSON event per line; the view replies `ready` after its first layout and `cancel` when the user confirms.
The view reads the selected summary, agent log, or transcript itself. The harness sends file paths, never file contents.
The view process gets a duplicate terminal descriptor, outside stdout/stderr capture.
While the view runs, the harness points its own stdin at `/dev/null`. Services inherit stdin, and a service that reads the terminal (for example `tsx watch`) takes key presses from the view.
The transcript routes console messages to the view while still saving their original text.
Cancel replies send one SIGINT through the existing cleanup path. The view ignores SIGINT, so it stays open during teardown.
The completed view stays open until `q`, then the final summary and transcript path print to the restored terminal.
Dashboard readiness requires the `ready` reply. Forced UI startup failures stop before eval setup; automatic mode reports the failure before selecting text output.
If the view process exits during a run, the runner stops through its cleanup path and saves the view's stderr in the transcript.
UI loop exceptions propagate through the worker, interrupt an active run once for cleanup, and are logged with their original traceback.

Every invocation that attempts an eval writes the combined stdout/stderr stream to `logs/harness/<timestamp>_<id>.log`.
An explanatory line identifies the full run transcript, followed by the log's unlabeled absolute path as the final line in both the transcript and terminal.
`logs/harness/latest.log` points to it.
Discovery-only `--list` invocations and argument errors do not write transcripts.

## Concurrency model

One `asyncio.Semaphore` on `EvalContext` bounds live sandboxes across every suite.
`base.py::task()` acquires it around exactly the sandbox-owning window and releases it before post-processing.

Two consequences worth internalizing:

- The per-case timeout is an `asyncio.wait_for` **inside** the slot. Braintrust's own `timeout` would have wrapped the whole task invocation, including time queued on the semaphore, killing cases that never got a sandbox.
- A second `team_setup_slots` semaphore covers the full demo-data clone plus optional case seeder. It has one permit on ordinary local machines and four when `CODER` or `CI` is set, so managed environments prepare cases faster without making setup concurrency follow Modal's unbounded sandbox capacity.
- The agent timeout begins after team setup. Waiting for either semaphore never consumes it.
- All turns share a monotonic poll deadline. The harness reserves up to 120 seconds, capped at one quarter of the case budget, for diagnostic recovery and cleanup before outer cancellation.
- Poll timeouts retain their stage and log counts in case metadata and local artifacts. They follow the existing scored-timeout path.
- One-shot suites never touch the sandbox semaphore; a separate global `one_shot_slots` semaphore bounds their concurrently running cases under the same acquire-once, budget-inside rules.

There are two event loops. The main loop owns the Temporal dev server, the suites, and the reporter.
The Temporal worker keeps its own loop on a daemon thread, and the two communicate only through `loop.call_soon_threadsafe`.

## Provider differences

|                     | docker                        | modal                     |
| ------------------- | ----------------------------- | ------------------------- |
| `SANDBOX_PROVIDER`  | `docker`                      | `MODAL_EVALS`             |
| Service URLs        | `host.docker.internal:<port>` | Tailscale Funnel URLs     |
| `start()`           | base-image freshness check    | Tailscale Funnel          |
| Local skills        | bind-mounted                  | baked into the image      |
| Default sandbox cap | 4                             | unbounded                 |
| Sandbox TTL         | default                       | case timeout plus margin  |
| Per-case safety net | container sweep               | task-tagged sandbox sweep |
| End-of-run cleanup  | container sweep               | task-tagged sandbox sweep |

`MODAL_EVALS` is the same `ModalSandbox` class under the dedicated `posthog-sandbox-evals` app, so eval image builds do not share an image cache with production or local development sandboxes.

The modal TTL override exists because under `TEST=1` the sandbox TTL equals the default per-case timeout, which would let Modal reap a slow case's sandbox exactly as it was finishing.
