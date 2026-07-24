# Working on the sandboxed eval harness

Read [`README.md`](README.md) first for the module map and boot sequence.
This file is only the set of invariants that are easy to break and expensive to debug, because breaking most of them produces a hang or a silently wrong result rather than an exception.

Verify a change with `python -m products.posthog_ai.eval_harness.harness --list` (imports every eval module, so it catches most breakage in seconds) before spending a real eval run on it.

## Import ordering

`__main__.py` calls `setup_django()` **before** importing `lifecycle`, and `lifecycle` is what pulls in everything that touches Django settings, the ORM, or the `products.tasks` facade.
Anything reachable from `__main__`'s top-level imports must therefore stay Django-free: today that is `cli.py`, `providers.py`, `tunnels.py`, `ports.py`, `env_preflight.py`, `requirements.py`, `transcript.py`, `log_sink.py`, and `django_env.py` itself, plus [`../engines/types.py`](../engines/types.py) — the stdlib-only neutral types `env_preflight` imports `EnvVarSpec` from. Keep `types.py` free of braintrust, Django, and pydantic for that reason.

This is why the port constants live in `ports.py` rather than in `services.py`, which imports Django.
If you add an import to one of those modules, check that `--list` still runs.

## Concurrency

The Braintrust-specific knobs below (`timeout`, `max_concurrency`, `QUIET_REPORTER`, `update`) are applied in one place — `BraintrustEngine.run_experiment` in [`../engines/braintrust.py`](../engines/braintrust.py), the sole `EvalEngine` implementation — and documented as obligations in its docstring. `_BaseEvalRun.run()` only hands the engine the cases, task, scorers, and metadata. A future engine (e.g. a PostHog-native one) owns its own equivalents.

- **Never give Braintrust a `timeout`.** `EvalAsync`'s timeout wraps the whole task invocation, including time queued on our concurrency semaphores, so it would kill cases that never started. The budget belongs in the `asyncio.wait_for` inside the slot.
- **Never let Braintrust's `max_concurrency` bind.** It is set to the case count so that the harness's own semaphores are the only limiters.
- **Acquire `ctx.sandbox_slots` exactly once per case**, around only the sandbox-owning window. It is not reentrant; a second acquisition inside the first deadlocks. `ctx.one_shot_slots` follows the same rules for one-shot cases: acquired once, `wait_for` budget inside, never both semaphores in one case.
- Hold `ctx.team_setup_slots` across both the demo-data clone and optional case setup hook. Some setup hooks write directly to ClickHouse, so releasing it between those phases defeats the RAM guard.
- Resolve the team-setup limit once through `HarnessOptions`: one permit normally and four when `CODER` or `CI` is set. Do not read those environment variables inside a case or make setup concurrency follow the sandbox limit.
- Keep scoring, log parsing, and span building _outside_ the slot. A sandbox that is being scored is a sandbox that someone else could be using.
- Every sync Django ORM call reached from async code goes through `asyncio.to_thread`. Do not set `DJANGO_ALLOW_ASYNC_UNSAFE` to make an error go away.

## Engines

`_BaseEvalRun.run()` builds an `ExperimentSpec` (cases, task, scorers, flags, metadata) and hands it to `ctx.engine.run_experiment`, which returns an engine-neutral `ExperimentResult` ([`../engines/types.py`](../engines/types.py)).
The engine is resolved once per run by `engines/registry.resolve_engine()` and shared via `EvalContext.engine`; there is no `--engine` flag until a second engine exists.
`BraintrustEngine` ([`../engines/braintrust.py`](../engines/braintrust.py)) is the only implementation and the sole runtime module that knows braintrust exists, alongside the deferred autoevals judge substrate in `../scorers/`.

Every engine owes the run base these obligations, pinned by the conformance suite ([`../test/test_engine_conformance.py`](../test/test_engine_conformance.py)):

- Never throttle or budget the task — the harness's own semaphores and `asyncio.wait_for` are the only limiters. The braintrust `timeout`/`max_concurrency` knobs above are how `BraintrustEngine` honors this.
- Persist `hooks.metadata` mutations onto `CaseResult.metadata`.
- Turn a task exception into `CaseResult.error` (a string) and exclude that case from aggregates.
- Preserve `score=None` per-case and exclude it from the means — `None` is "skipped", `0.0` is "failed".
- Print nothing to the shared stdout (braintrust's `QUIET_REPORTER` is how it stays quiet), and accumulate history under a stable `project_name`.

A new engine implements the `EvalEngine` protocol ([`../engines/base.py`](../engines/base.py)) — `name`, `supports_public_experiments`, `required_env()`, `run_experiment(spec)` — registers in `engines/registry.py`, joins the conformance fixture list, and must pass it unchanged.

## Terminal output

`ProgressReporter` owns formatted harness messages and holds a lock, because suites run concurrently and would otherwise interleave.
Do not add bare `print` calls to `base.py` or the run lifecycle; route them through the reporter.
The same lock guards the `eval_results.jsonl` append, where concurrent writes would tear a line in half.

`QUIET_REPORTER` exists so each Braintrust experiment does not dump its own score table into the shared stream.
Its callbacks are called synchronously by `EvalAsync` and must not be coroutines.

`RunTranscript` owns the outer stdout/stderr tee for every real run.
It must contain the complete plain-text terminal stream, and both the terminal and transcript must end with the same unlabeled absolute transcript path.
The preceding line must identify that path as the full stdout/stderr run transcript.
Keep final summary rendering after suite teardown and call `logging.shutdown()` before `RunTranscript.finish()`, so cleanup or buffered logging cannot write after the path.
`--list` and argparse errors intentionally bypass transcript creation.

Only the final overall status may say `PASS` or `FAIL`.
Successful cases, experiments, and suites say `DONE`; `TIMEOUT`, `ERROR`, and `CRASH` keep outcome and infrastructure failures distinct.

## Suites

Suites are discovered by convention, not registered: any coroutine named `eval_*` defined in a file named `eval_*.py` under `products/posthog_ai/evals/` or a `products/<product>/evals/` tree.
A suite takes one argument, `ctx: EvalContext`, and returns `None`.

A module declares how its suites execute with a module-level `SUITE_KIND` (`requirements.SuiteKind`); absent means sandboxed.
The kind decides which infrastructure the harness boots (`requirements.INFRA_BY_KIND`) and which env models preflight validates (`env_preflight.ENV_MODELS_BY_KIND`) — an under-declared kind fails loudly when the runner narrows the `EvalContext` fields its infra never populated.

Because suites do not return their Braintrust result, `base.py` hands the summary to the reporter via `record_summary`.
That is the only path by which the final table and the JSONL export see per-scorer scores — for every suite kind.

A crashing suite must never take down the others: `lifecycle._run_suite` catches `Exception` per suite and the run exits non-zero at the end.
Do not widen that to `BaseException`, which would swallow `CancelledError` and `KeyboardInterrupt`.

## Scorers

`base.py` adds `ExitCodeZero` to every experiment before optional tracing wraps the scorers.
Suites must not declare it themselves, and the constructor rejects an explicit duplicate.

Every scorer implements exactly one branch — never both `_run_eval_sync` and `_run_eval_async`.
Braintrust's `EvalAsync` always dispatches through `eval_async`, and the base `Scorer`'s default `_run_eval_async` already delegates to `_run_eval_sync`, so a second branch is either dead code or a silently divergent copy.

- Deterministic scorers subclass `Scorer` and implement `_run_eval_sync` only; the base class supplies the async path (and the sync path is what the pytest scorer tests call).
- LLM judges subclass `scorers.JudgedScorer` and implement `_prepare` only; the shared base owns the short-circuit/error-mapping async branch, and `AsyncOnlyScorerMixin` makes the unused sync branch raise instead of running without `_prepare`.
- Async-only classes that subclass `Scorer` directly (`TracedScorer`, hybrids like `DuplicateUniqueFlagKey`) need `AsyncOnlyScorerMixin` first in their bases — `_run_eval_sync` is abstract on `Scorer`, and the mixin is what satisfies it.

## Teardown

Bootstrap registers teardown on an `ExitStack` as each resource comes up, so a failure halfway through still unwinds what already started.
`atexit` hooks plus the subprocess manager's signal handlers cover Ctrl-C, where neither stack unwinds.

After any change, a Ctrl-C mid-run must leave no listeners on 18000 / 13308 / 18787 / 18788 / 14040 / 15051 / 15052, no `task-sandbox-*` containers, and no Temporal dev server.

Three layers tear a case's sandbox down, outermost last:

- Every case signals its `ProcessTaskWorkflow` with a terminal status and waits for the workflow result, which includes the workflow's own `cleanup_sandbox` call.
- If the workflow does not finish within the completion grace period, the runner cancels it and waits once more. An otherwise successful case becomes an infrastructure error when neither wait confirms a terminal state; existing failures and timeouts keep their original outcome.
- `provider.cleanup_case(task_id)` then runs as a per-case safety net. Docker reclaims the case's container by name, while Modal terminates sandboxes carrying that exact `task_id` tag.

`provider.cleanup()` runs through the normal `ExitStack` and through `atexit` as an interruption fallback, sweeping anything the above missed: leftover Docker containers by name and leftover Modal sandboxes under the eval app.
Both sweeps are scoped to this run's own tasks: the runner registers each task id via `provider.register_task`, and cleanup filters on that set — by container name on Docker, by the `task_id` sandbox tag on Modal.
So a dev-stack task sandbox or a second concurrent eval run sharing the provider is never reaped, and a run that started nothing sweeps nothing.

## Providers

Provider differences belong in `providers.py`, not in `if provider == "docker"` branches scattered through `lifecycle.py`.
Add a `SandboxProviderStrategy` method rather than a conditional.
Per-case teardown is one such method (`cleanup_case`): the runner calls it after every case, so a docker-only concern like reclaiming a leftover container never leaks into `runner.py` or fires on a Modal run.

`preflight()` must catch a missing prerequisite before any infrastructure boots, and its message must say how to fix it.
A missing ngrok authtoken, for instance, otherwise surfaces only as a 60-second tunnel timeout.

The chosen provider must reach `settings.SANDBOX_PROVIDER` **before `django.setup()`**, which is why `__main__` sets it in the environment (from `SANDBOX_PROVIDER_SETTING`) rather than relying only on the async-phase `override_settings`.
`products.tasks` resolves the sandbox class from that setting exactly once and caches it in module globals, so the first `Sandbox` access wins for the whole process.
`.env` ships `SANDBOX_PROVIDER=docker`, so setting it late let a `--provider modal` run cache `DockerSandbox` and execute the agent in a local container while still pointing it at the ngrok URLs.
Docker mode hid this because the cached value already matched.
Modal evals use the `MODAL_EVALS` backend, whose sandbox class is pinned to the `posthog-sandbox-evals` Modal app.

`PERSONHOG_ADDR` follows the same rule for the same reason: the personhog client is a cached singleton keyed off settings at its first call, and bootstrap-phase reads run before the async-phase `override_settings`.
`__main__` therefore sets it in the environment before `django.setup()`, pointing at the harness's own router on 15052 — which also shields the run from a `PERSONHOG_ADDR` leaked out of a sourced dev `.env`, where reads would silently hit the dev persons DB.

Env loading follows the same before-`django.setup()` rule: `__main__` loads the repo-root `.env` via `env_preflight.load_env_file()` (a stdlib parser that decodes `.env`'s quoted/escaped PEM keys, which hogli's line-based parser cannot represent), never overriding variables the shell or hogli's env loading already exported.
`products/signals/eval/conftest.py` reuses the same loader, so it is the repo's one `.env` parser — keep it dependency-free.
The explicit `SANDBOX_PROVIDER` / `PERSONHOG_ADDR` assignments come after the load, so they trump any env file on every path.

`setup_django()` also forces `SELF_CAPTURE=0` before `django.setup()`. The ASGI app must not re-enable the global SDK with the local development personal API key during evals; eval trace emission uses the harness's explicit regional client instead.
Required variables are then validated by `env_preflight.validate_eval_env()` at the top of `lifecycle.run()`, before any infrastructure boots — add new hard env requirements to the per-kind env models there (`SandboxEvalEnv`, `OneShotEvalEnv`), or, for engine-specific keys, to the engine's `required_env()` (`BRAINTRUST_API_KEY` lives on `BraintrustEngine`), which `lifecycle` threads in via the `engine_env` argument — not as ad-hoc checks scattered through bootstrap.

## pytest

This tree is not pytest: do not add a `conftest.py` here and do not import `pytest` in harness or eval modules.
The harness's own unit tests live in [`../test/`](../test/), which is ordinary pytest.
Suite files under the `evals/` trees are never collected by pytest either — its default `python_files` only matches `test_*.py`.
`ee/hogai/eval/ci/` and `ee/hogai/eval/offline/` are still pytest and still import `data_setup` from this package, so keep that module's pytest-independence intact.
