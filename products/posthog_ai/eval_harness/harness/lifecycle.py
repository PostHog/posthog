from __future__ import annotations

import time
import atexit
import asyncio
import logging
from collections.abc import Sequence
from contextlib import AsyncExitStack, ExitStack

from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

import posthoganalytics
from posthoganalytics import Posthog

from posthog.ph_client import get_client

from products.tasks.backend.temporal.process_task.utils import get_reasoning_effort_error

from ..engines.base import EvalEngine
from ..engines.registry import resolve_engine
from .cli import DEFAULT_ONE_SHOT_CONCURRENCY, HarnessOptions
from .context import EvalContext
from .demo_data import SandboxedDemoData, ensure_demo_ready
from .discovery import EvalSuite, discover_suites
from .django_env import EvalDatabase
from .env_preflight import validate_eval_env
from .live_server import EvalLiveServer
from .ports import DJANGO_LIVE_PORT
from .providers import PreflightError, SandboxProviderStrategy, build_provider
from .reporting import ProgressReporter, SuiteRunResult
from .requirements import Infra, infra_union
from .services import (
    build_local_skills,
    ensure_personhog_binaries,
    package_local_skills_archive,
    start_llm_gateway,
    start_mcp_server,
    start_personhog,
    start_skill_archive_server,
    stop_all_subprocesses,
)
from .temporal_env import (
    TemporalWorkerThread,
    start_temporal_env,
    temporal_client_target,
    temporal_task_queue,
    terminate_stale_workflows,
)

logger = logging.getLogger(__name__)


class SandboxedEvalHarness:
    """Boots the shared eval infrastructure once, then runs every selected suite concurrently.

    Two phases. The sync bootstrap runs before any event loop exists, because
    Django's async-safety guard rejects sync ORM calls from an async context and
    most of the setup is ORM-heavy. The async phase owns Temporal, the suites,
    and the shared semaphores that bound sandbox load and serialize team setup.
    """

    def __init__(self, options: HarnessOptions) -> None:
        self.options = options
        self.provider: SandboxProviderStrategy | None = None
        # The execution/reporting backend for this run. No --engine flag yet, so
        # this is the registry default; it feeds preflight and every suite's run.
        self._engine: EvalEngine = resolve_engine()
        self._stack = ExitStack()
        self._database: EvalDatabase | None = None
        self._live_server: EvalLiveServer | None = None
        self._posthog_client: Posthog | None = None
        self._demo_data: SandboxedDemoData | None = None

    def run(self) -> int:
        # Discover before anything is provisioned: a typo'd selector should cost a
        # module import, not a database build and a Hedgebox seed.
        suites = discover_suites(self.options.selectors)

        if self.options.list_only:
            for suite in suites:
                print(f"{suite.id}  [{suite.kind.value}]")  # noqa: T201
            return 0

        # Boot only what the selected suites' kinds require: a one-shot-only run
        # never pays for (or fails on) sandbox infrastructure.
        kinds = {suite.kind for suite in suites}
        required = infra_union(kinds)

        if Infra.SANDBOX not in required and self.options.sandbox_flags_set:
            flags = ", ".join(self.options.sandbox_flags_set)
            raise PreflightError(f"{flags}: no selected suite is sandboxed, so sandbox flags have no effect")

        reporter = ProgressReporter(total_suites=len(suites))
        reporter.print_run_header(
            provider=self.options.provider,
            agent_runtime=self.options.agent_runtime,
            agent_model=self.options.agent_model,
            max_sandboxes=self.options.max_sandboxes,
            trials=self.options.trials,
        )

        started = time.monotonic()
        results: list[SuiteRunResult] | None = None
        interrupted = False
        try:
            validate_eval_env(self.options.agent_runtime, kinds=kinds, engine_env=self._engine.required_env())
            if Infra.SANDBOX in required:
                self.provider = build_provider(
                    self.options.provider,
                    keep_containers=self.options.keep_sandbox_containers,
                    rebuild_image=self.options.rebuild_sandbox_image,
                )
                self._validate_agent_options()
                self.provider.preflight()
            if Infra.PERSONHOG in required:
                ensure_personhog_binaries()
            self._bootstrap(required)
            results = asyncio.run(self._run_suites(suites, required, reporter))
        except KeyboardInterrupt:
            logger.warning("Interrupted, tearing down")
            interrupted = True
        finally:
            try:
                self._stack.close()
            finally:
                atexit.unregister(stop_all_subprocesses)
                if self.provider is not None:
                    atexit.unregister(self.provider.cleanup)

        duration_seconds = time.monotonic() - started
        if interrupted:
            reporter.print_incomplete_summary(status="INTERRUPTED", duration_seconds=duration_seconds)
            return 130
        if results is None:
            raise RuntimeError("Sandboxed eval run finished without suite results")

        exit_code = self._exit_code(results, reporter)
        reporter.print_final_summary(
            results,
            exit_code=exit_code,
            fail_under=self.options.fail_under,
            duration_seconds=duration_seconds,
        )
        return exit_code

    def _exit_code(self, results: Sequence[SuiteRunResult], reporter: ProgressReporter) -> int:
        if any(result.status == "crashed" for result in results):
            return 1
        if self.options.fail_under is None:
            return 0
        mean = reporter.mean_score()
        if mean is None or mean < self.options.fail_under:
            return 1
        return 0

    def _validate_agent_options(self) -> None:
        """Validate runtime/model/effort with the tasks helpers, which need Django loaded.

        ``cli.py`` is Django-free by invariant, so this is the earliest point the real
        validation can run — still before any infrastructure boots.
        """
        error = get_reasoning_effort_error(
            self.options.agent_runtime, self.options.agent_model, self.options.reasoning_effort
        )
        if error:
            raise PreflightError(error)

    def _bootstrap(self, required: frozenset[Infra]) -> None:
        """Stand up everything the selected suites share. Teardown is registered in
        reverse on the stack, so what wasn't started is never torn down."""
        # Belt and braces for the SIGINT / SIGTERM paths, where the ExitStack never unwinds.
        atexit.register(stop_all_subprocesses)
        if self.provider is not None:
            atexit.register(self.provider.cleanup)
            self._stack.callback(self.provider.cleanup)

        if Infra.DATABASE in required:
            database = EvalDatabase(keepdb=not self.options.create_db)
            database.setup()
            self._stack.callback(database.teardown)
            self._database = database

        if Infra.PERSONHOG in required:
            # Bring personhog up before the live server and demo seeding: those bootstrap
            # reads go through the router, and a dead router would poison personhog's 30s
            # negative group-types cache for the rest of the run.
            self._stack.callback(start_personhog())

        if Infra.LIVE_SERVER in required:
            live_server = EvalLiveServer(DJANGO_LIVE_PORT)
            self._stack.callback(live_server.stop)
            self._live_server = live_server

        if Infra.LLM_GATEWAY in required:
            assert self._live_server is not None
            self._stack.callback(start_llm_gateway(self._live_server.url))
        if Infra.MCP_SERVER in required:
            assert self._live_server is not None

            # Both delivery modes use rendered skills from this checkout, never a
            # previously published bundle.
            skills_dir = build_local_skills(set_bind_mount_env=self.options.provider == "docker")
            skill_archive_url: str | None = None
            if self.options.skill_delivery == "exec":
                skill_archive = package_local_skills_archive(skills_dir)
                skill_archive_url, stop_skill_archive = start_skill_archive_server(skill_archive)
                self._stack.callback(stop_skill_archive)
            self._stack.callback(
                start_mcp_server(
                    self._live_server.url,
                    skill_archive_url,
                    exec_skills_enabled=self.options.skill_delivery == "exec",
                )
            )

        if Infra.SANDBOX in required:
            assert self.provider is not None
            # Modal sandboxes live off-host, so the three services above have to be
            # publicly reachable before any settings pointing at them are computed.
            self.provider.start(self._stack)

        self._posthog_client = get_client("US")
        if self._posthog_client is not None:
            self._stack.callback(self._posthog_client.shutdown)

        if Infra.DEMO_DATA in required:
            assert self._database is not None
            self._demo_data = ensure_demo_ready(
                blocker=self._database.blocker,
                agent_model=self.options.agent_model,
                agent_runtime=self.options.agent_runtime,
                reasoning_effort=self.options.reasoning_effort,
                sandbox_timeout_seconds=(
                    self.provider.sandbox_timeout_seconds(self.options.per_case_timeout_seconds)
                    if self.provider is not None
                    else None
                ),
            )

    async def _run_suites(
        self, suites: Sequence[EvalSuite], required: frozenset[Infra], reporter: ProgressReporter
    ) -> list[SuiteRunResult]:
        async with AsyncExitStack() as stack:
            overrides: dict[str, object] = {}
            if Infra.LIVE_SERVER in required:
                overrides.update(
                    DEBUG=True,  # Required for sandbox URL validation to allow http://localhost
                    # The sandbox reaches the Django live server with a non-loopback
                    # Host header (host.docker.internal, or the ngrok domain); allow it
                    # (test-only) so the agent's event-ingest stream isn't rejected with
                    # an invalid-host 400.
                    ALLOWED_HOSTS=["*"],
                )
            if Infra.SANDBOX in required:
                assert self.provider is not None
                temporal_env = await start_temporal_env()
                stack.push_async_callback(temporal_env.shutdown)
                temporal_host, temporal_port = temporal_client_target(temporal_env)
                overrides.update(
                    TEMPORAL_HOST=temporal_host,
                    TEMPORAL_PORT=temporal_port,
                    TEMPORAL_NAMESPACE=settings.TEMPORAL_NAMESPACE,
                    TEMPORAL_CLIENT_CERT=None,
                    TEMPORAL_CLIENT_KEY=None,
                    # Keep eval workflows off any dev worker already polling the normal tasks queue.
                    TASKS_TASK_QUEUE=temporal_task_queue(),
                    **self.provider.settings_overrides(),
                )

            if overrides:
                stack.enter_context(override_settings(**overrides))
            stack.enter_context(patch.object(posthoganalytics, "feature_enabled", return_value=True))

            if Infra.SANDBOX in required:
                # Stale workflows from a prior run make the worker provision sandboxes for
                # runs that no longer exist, delaying the real eval workflows by 30-60s.
                await terminate_stale_workflows()

                worker = TemporalWorkerThread()
                worker.start()
                stack.callback(worker.stop)

            ctx = self._build_context(required, reporter)

            if Infra.SANDBOX in required:
                logger.info(
                    "Running %d suite(s) on provider=%s with skill_delivery=%s and %d sandbox slot(s)",
                    len(suites),
                    self.options.provider,
                    self.options.skill_delivery,
                    self.options.max_sandboxes,
                )
            else:
                logger.info("Running %d suite(s) without sandbox infrastructure", len(suites))
            results = await asyncio.gather(*(self._run_suite(suite, ctx) for suite in suites))
        return results

    def _build_context(self, required: frozenset[Infra], reporter: ProgressReporter) -> EvalContext:
        if Infra.DEMO_DATA in required and self._demo_data is None:
            raise RuntimeError("_bootstrap() must run before the eval context is built")
        return EvalContext(
            provider=self.options.provider,
            provider_strategy=self.provider,
            agent_model=self.options.agent_model,
            agent_runtime=self.options.agent_runtime,
            skill_delivery=self.options.skill_delivery,
            reasoning_effort=self.options.reasoning_effort,
            case_filter=self.options.case_filter,
            demo_data=self._demo_data,
            posthog_client=self._posthog_client,
            sandbox_slots=asyncio.Semaphore(self.options.max_sandboxes) if Infra.SANDBOX in required else None,
            team_setup_slots=asyncio.Semaphore(self.options.team_setup_concurrency),
            one_shot_slots=asyncio.Semaphore(DEFAULT_ONE_SHOT_CONCURRENCY),
            reporter=reporter,
            engine=self._engine,
            per_case_timeout_seconds=self.options.per_case_timeout_seconds,
            trials=self.options.trials,
        )

    async def _run_suite(self, suite: EvalSuite, ctx: EvalContext) -> SuiteRunResult:
        """Run one suite, absorbing its failures so a crash never takes the others down."""
        await ctx.reporter.suite_started(suite.id)
        started = time.monotonic()
        try:
            await suite.fn(ctx)
        except Exception as e:
            logger.exception("Eval suite %s crashed", suite.id)
            result = SuiteRunResult(
                suite_id=suite.id,
                status="crashed",
                error=e,
                duration_seconds=time.monotonic() - started,
            )
        else:
            result = SuiteRunResult(
                suite_id=suite.id,
                status="passed",
                duration_seconds=time.monotonic() - started,
            )
        await ctx.reporter.suite_finished(result)
        return result
