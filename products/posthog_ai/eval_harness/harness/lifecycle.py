from __future__ import annotations

import os
import time
import atexit
import asyncio
import hashlib
import logging
import tempfile
import subprocess
from collections.abc import Sequence
from contextlib import AsyncExitStack, ExitStack
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

import posthoganalytics
from posthoganalytics import Posthog

from posthog.ph_client import get_client

from products.tasks.backend.constants import MCP_EXEC_SKILLS_FEATURE_FLAG
from products.tasks.backend.logic.services.local_skills import (
    ENV_EVAL_SKILLS_MANIFEST,
    ENV_LOCAL_SKILLS_HOST_PATH,
    LocalSkillsCache,
)
from products.tasks.backend.temporal.process_task.utils import get_reasoning_effort_error

from ..engines.base import EvalEngine
from ..engines.registry import resolve_engine
from .cli import (
    DEFAULT_ONE_SHOT_CONCURRENCY,
    DEFAULT_SKILL_DELIVERY,
    MULTI_TURN_CASE_TIMEOUT_MULTIPLIER,
    HarnessOptions,
    SkillDelivery,
)
from .context import EvalContext
from .demo_data import SandboxedDemoData, ensure_demo_ready
from .discovery import MULTI_TURN_MODULE_MARKER, REPO_ROOT, EvalSuite, discover_suites
from .django_env import EvalDatabase
from .env_preflight import validate_eval_env
from .kernel_sandboxes import reclaim_kernels
from .live_server import EvalLiveServer
from .offline_delivery import OfflineEvalDelivery
from .ports import AI_GATEWAY_REDIS_URL, DJANGO_LIVE_PORT
from .providers import PreflightError, SandboxProviderStrategy, build_provider
from .reporting import ProgressReporter, SuiteRunResult
from .requirements import Infra, infra_union
from .run_report import RunReport
from .skill_snapshot import SkillSnapshot

if TYPE_CHECKING:
    from .dashboard import EvalDashboard
from .services import (
    EVAL_AI_PRODUCT,
    LONG_LIVED_SUBPROCESSES,
    build_local_skills,
    ensure_ai_gateway_binary,
    ensure_personhog_binaries,
    maintain_ai_gateway_mint_key,
    provision_ai_gateway_mint_key,
    start_ai_gateway,
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


def eval_feature_enabled(
    key: str, *_args: object, skill_delivery: SkillDelivery = DEFAULT_SKILL_DELIVERY, **_kwargs: object
) -> bool:
    """Stands in for `posthoganalytics.feature_enabled` so evals exercise flagged code paths."""
    if key == MCP_EXEC_SKILLS_FEATURE_FLAG:
        return skill_delivery == "exec"
    return True


def _git(*args: str) -> str | None:
    """Stdout of a git command run in the checkout under test; ``None`` when git fails."""
    # GIT_DIR, GIT_WORK_TREE and friends would point git away from REPO_ROOT.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    try:
        result = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, env=env, check=True, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def _worktree_dirty() -> bool | None:
    """Whether tracked files differ from ``HEAD``; ``None`` when git can't tell."""
    status = _git("status", "--porcelain", "--untracked-files=no")
    return None if status is None else bool(status)


class SandboxedEvalHarness:
    """Boots the shared eval infrastructure once, then runs every selected suite concurrently.

    Two phases. The sync bootstrap runs before any event loop exists, because
    Django's async-safety guard rejects sync ORM calls from an async context and
    most of the setup is ORM-heavy. The async phase owns Temporal, the suites,
    and the shared semaphores that bound sandbox load and serialize team setup.
    """

    def __init__(self, options: HarnessOptions, *, dashboard: EvalDashboard | None = None) -> None:
        self.options = options
        self._dashboard = dashboard
        self.provider: SandboxProviderStrategy | None = None
        # The execution/reporting backend for this run. No --engine flag yet, so
        # this is the registry default; it feeds preflight and every suite's run.
        self._engine: EvalEngine = resolve_engine()
        self._stack = ExitStack()
        self._database: EvalDatabase | None = None
        self._live_server: EvalLiveServer | None = None
        self._posthog_client: Posthog | None = None
        self._demo_data: SandboxedDemoData | None = None
        self._offline_delivery: OfflineEvalDelivery | None = None
        self._ai_gateway_mint_key: str | None = None
        self._skills_snapshot: SkillSnapshot | None = None
        # Capture the revision before any eval starts so every result describes the same run.
        self._git_sha = _git("rev-parse", "HEAD")
        self._git_dirty = _worktree_dirty()

    def run(self) -> int:
        # Discover before anything is provisioned: a typo'd selector should cost a
        # module import, not a database build and a Hedgebox seed.
        suites = discover_suites(self.options.selectors)

        if self.options.list_only:
            for suite in suites:
                print(f"{suite.id}  [{suite.kind.value}]")  # noqa: T201
            return 0

        if (
            self.options.skill_snapshot_report is not None
            and self.options.results_file is not None
            and self.options.skill_snapshot_report.resolve() == self.options.results_file.resolve()
        ):
            raise PreflightError("--skill-snapshot-report and --results-file must use different paths")

        # Multi-turn cases poll once per turn, each poll with its own budget, so
        # their per-case budget must scale with the turn count. Multi-turn modules
        # declare the marker at module level (see discovery._collect_suites).
        multi_turn_modules = {
            suite.module_name for suite in suites if getattr(suite.fn, MULTI_TURN_MODULE_MARKER, False)
        }
        if multi_turn_modules:
            scaled = self.options.per_case_timeout_seconds * MULTI_TURN_CASE_TIMEOUT_MULTIPLIER
            logger.warning(
                "Multi-turn eval module(s) %s selected: scaling --case-timeout from %ds to %ds",
                sorted(multi_turn_modules),
                self.options.per_case_timeout_seconds,
                scaled,
            )
            self.options = replace(self.options, per_case_timeout_seconds=scaled)

        # Boot only what the selected suites' kinds require: a one-shot-only run
        # never pays for (or fails on) sandbox infrastructure.
        kinds = {suite.kind for suite in suites}
        required = infra_union(kinds)

        if Infra.SANDBOX not in required and self.options.sandbox_flags_set:
            flags = ", ".join(self.options.sandbox_flags_set)
            raise PreflightError(f"{flags}: no selected suite is sandboxed, so sandbox flags have no effect")

        reporter = ProgressReporter(
            total_suites=len(suites),
            verbose=self.options.verbose,
            dashboard=self._dashboard,
            revision=self._git_sha,
            worktree_dirty=self._git_dirty,
        )
        reporter.write_run_report(self.options, suites, exit_code=1, duration_seconds=0)
        reporter.print_run_header(
            provider=self.options.provider,
            agent_runtime=self.options.agent_runtime,
            agent_model=self.options.agent_model,
            max_sandboxes=self.options.max_sandboxes,
            trials=self.options.trials,
            case_timeout_seconds=self.options.per_case_timeout_seconds,
        )

        started = time.monotonic()
        results: list[SuiteRunResult] | None = None
        interrupted = False
        self._offline_delivery = OfflineEvalDelivery(reporter)
        with asyncio.Runner() as runner:
            try:
                reporter.setup_started("check configuration")
                validate_eval_env(
                    self.options.agent_runtime,
                    kinds=kinds,
                    engine_env=self._engine.required_env(no_send_logs=all(suite.no_send_logs for suite in suites)),
                )
                if Infra.SANDBOX in required:
                    self.provider = build_provider(
                        self.options.provider,
                        keep_containers=self.options.keep_sandbox_containers,
                        rebuild_image=self.options.rebuild_sandbox_image,
                    )
                    self._validate_agent_options()
                    self.provider.preflight()
                if self.options.check_only:
                    reporter.write_run_report(
                        self.options, suites, exit_code=0, duration_seconds=time.monotonic() - started
                    )
                    return 0
                if Infra.PERSONHOG in required:
                    reporter.setup_started("build personhog")
                    ensure_personhog_binaries()
                if Infra.AI_GATEWAY in required:
                    reporter.setup_started("build ai-gateway")
                    ensure_ai_gateway_binary()
                reporter.setup_started("start shared services and prepare demo data")
                self._bootstrap(required, reporter)
                if self._dashboard:
                    self._dashboard.setup_finished()
                results = runner.run(self._run_suites(suites, required, reporter))
            except KeyboardInterrupt:
                logger.warning("Interrupted, tearing down")
                interrupted = True
            finally:
                try:
                    if self._dashboard:
                        self._dashboard.set_stage("Cleaning up shared services")
                    try:
                        runner.run(self._offline_delivery.pause())
                    finally:
                        self._stack.close()
                except KeyboardInterrupt:
                    interrupted = True
                finally:
                    atexit.unregister(stop_all_subprocesses)
                    if self.provider is not None:
                        atexit.unregister(self.provider.cleanup)
                    try:
                        runner.run(
                            self._offline_delivery.cancel()
                            if interrupted or results is None
                            else self._offline_delivery.drain()
                        )
                    except KeyboardInterrupt:
                        interrupted = True
                        runner.run(self._offline_delivery.cancel())
                    finally:
                        if not self.options.check_only:
                            reporter.write_run_report(
                                self.options,
                                suites,
                                exit_code=130 if interrupted else 1,
                                duration_seconds=time.monotonic() - started,
                            )

        duration_seconds = time.monotonic() - started
        if interrupted:
            reporter.print_incomplete_summary(status="INTERRUPTED", duration_seconds=duration_seconds)
            reporter.write_run_report(self.options, suites, exit_code=130, duration_seconds=duration_seconds)
            return 130
        if results is None:
            raise RuntimeError("Sandboxed eval run finished without suite results")

        exit_code = self._exit_code(results, reporter)
        reporter.write_run_report(self.options, suites, exit_code=exit_code, duration_seconds=duration_seconds)
        reporter.print_final_summary(
            results,
            exit_code=exit_code,
            fail_under=self.options.fail_under,
            duration_seconds=duration_seconds,
        )
        return exit_code

    def _exit_code(self, results: Sequence[SuiteRunResult], reporter: ProgressReporter) -> int:
        if any(result.status == "crashed" for result in results) or reporter.has_case_errors():
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

    def _bootstrap(self, required: frozenset[Infra], reporter: ProgressReporter) -> None:
        """Stand up everything the selected suites share. Teardown is registered in
        reverse on the stack, so what wasn't started is never torn down."""
        self._stack.enter_context(override_settings(AI_GATEWAY_REDIS_URL=None))
        LONG_LIVED_SUBPROCESSES.startup_retries = self.options.infrastructure_retries
        # Belt and braces for the SIGINT / SIGTERM paths, where the ExitStack never unwinds.
        atexit.register(stop_all_subprocesses)
        if self.provider is not None:
            atexit.register(self.provider.cleanup)
            self._stack.callback(self.provider.cleanup)

        if Infra.DATABASE in required:
            reporter.setup_started("prepare eval databases")
            database = EvalDatabase(keepdb=not self.options.create_db)
            database.setup()
            self._stack.callback(database.teardown)
            self._database = database

        if Infra.PERSONHOG in required:
            reporter.setup_started("start personhog")
            # Bring personhog up before the live server and demo seeding: those bootstrap
            # reads go through the router, and a dead router would poison personhog's 30s
            # negative group-types cache for the rest of the run.
            self._stack.callback(start_personhog())

        if Infra.LIVE_SERVER in required:
            reporter.setup_started("start Django server")
            live_server = EvalLiveServer(DJANGO_LIVE_PORT)
            self._stack.callback(live_server.stop)
            self._live_server = live_server

        if Infra.AI_GATEWAY in required:
            reporter.setup_started("start AI gateway")
            self._stack.callback(start_ai_gateway())
            self._stack.enter_context(override_settings(AI_GATEWAY_REDIS_URL=AI_GATEWAY_REDIS_URL))
        # Seed before building skills: HogQL examples in skill templates render against a Team,
        # and on a fresh test database the master team is the first one that exists.
        if Infra.DEMO_DATA in required:
            reporter.setup_started("prepare demo data")
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

        if Infra.MCP_SERVER in required:
            reporter.setup_started("build skills and start MCP server")
            assert self._live_server is not None

            # A private build directory keeps installed bundles and concurrent builds out of the run.
            output_paths = tuple(
                path
                for path in (
                    self.options.results_file,
                    self.options.skill_snapshot_report,
                    self.options.skill_snapshot_output_dir,
                )
                if path is not None
            )
            source_sha256 = SkillSnapshot.source_fingerprint(
                Path(settings.BASE_DIR), LocalSkillsCache().source_sha256, excluded_paths=output_paths
            )
            if self.options.skill_snapshot_report is not None:
                saved = RunReport.model_validate_json(self.options.skill_snapshot_report.read_text())
                if (
                    saved.skills_source_sha256 != source_sha256
                    or saved.revision != self._git_sha
                    or not saved.skills_archive_path
                    or not saved.skills_sha256
                ):
                    raise RuntimeError("Saved skill snapshot does not match this checkout's branch skill sources")
                self._skills_snapshot = SkillSnapshot.restore(
                    Path(saved.skills_archive_path),
                    self._stack,
                    expected_sha256=saved.skills_sha256,
                    source_sha256=source_sha256,
                    retain=self.options.keep_sandbox_containers,
                )
            else:
                skill_build_dir = Path(
                    self._stack.enter_context(tempfile.TemporaryDirectory(prefix="posthog-eval-build-"))
                )
                skills_dir = build_local_skills(set_bind_mount_env=False, output_dir=skill_build_dir)
                self._skills_snapshot = SkillSnapshot.capture(
                    skills_dir,
                    self._stack,
                    source_sha256=source_sha256,
                    retain=self.options.keep_sandbox_containers,
                )
            if (
                SkillSnapshot.source_fingerprint(
                    Path(settings.BASE_DIR), LocalSkillsCache().source_sha256, excluded_paths=output_paths
                )
                != source_sha256
            ):
                raise RuntimeError("Branch skill sources changed while preparing the eval snapshot")
            skills_dir = self._skills_snapshot.directory
            self._stack.enter_context(
                patch.dict(
                    os.environ,
                    {
                        ENV_LOCAL_SKILLS_HOST_PATH: str(skills_dir),
                        ENV_EVAL_SKILLS_MANIFEST: str(self._skills_snapshot.manifest_path),
                    },
                )
            )
            reporter.set_skill_snapshot(self._skills_snapshot)
            skill_archive_url: str | None = None
            skill_archive_sha256: str | None = None
            if self.options.skill_delivery == "exec":
                skill_archive = self._skills_snapshot.archive_path
                skill_archive_sha256 = hashlib.sha256(skill_archive.read_bytes()).hexdigest()
                skill_archive_url, stop_skill_archive = start_skill_archive_server(skill_archive)
                self._stack.callback(stop_skill_archive)
            self._stack.callback(
                start_mcp_server(
                    self._live_server.url,
                    skill_archive_url,
                    exec_skills_enabled=self.options.skill_delivery == "exec",
                    skill_archive_sha256=skill_archive_sha256,
                )
            )

        if Infra.SANDBOX in required:
            reporter.setup_started("prepare sandbox provider")
            assert self.provider is not None
            # Modal sandboxes live off-host, so the three services above have to be
            # publicly reachable before any settings pointing at them are computed.
            self.provider.start(self._stack)

        self._posthog_client = get_client("US")
        if self._posthog_client is not None:
            self._stack.callback(self._posthog_client.shutdown)

        if Infra.AI_GATEWAY in required:
            assert self._demo_data is not None and self._database is not None
            with self._database.blocker.unblock():
                self._ai_gateway_mint_key = provision_ai_gateway_mint_key(
                    self._demo_data.master_team_id, agent_model=self.options.agent_model
                )

    async def _run_suites(
        self, suites: Sequence[EvalSuite], required: frozenset[Infra], reporter: ProgressReporter
    ) -> list[SuiteRunResult]:
        async with AsyncExitStack() as stack:
            if Infra.AI_GATEWAY in required:
                assert self._demo_data is not None and self._ai_gateway_mint_key is not None
                await stack.enter_async_context(
                    maintain_ai_gateway_mint_key(self._demo_data.master_team_id, self._ai_gateway_mint_key)
                )
            overrides: dict[str, object] = {}
            if Infra.LIVE_SERVER in required:
                overrides.update(
                    DEBUG=True,  # Required for sandbox URL validation to allow http://localhost
                    # The sandbox reaches the Django live server with a non-loopback
                    # Host header (host.docker.internal, or the Tailscale Funnel host); allow it
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
                    # Notebook kernel runs dispatch onto the general-purpose queue. Pointing it at
                    # the same per-process queue lets the single eval worker serve both, and keeps
                    # those workflows off a dev worker the same way.
                    GENERAL_PURPOSE_TASK_QUEUE=temporal_task_queue(),
                    # The harness never starts run_task_workflow_dispatcher, so an outbox dispatch would
                    # leave every case parked in QUEUED until the case's poll budget runs out.
                    TASKS_WORKFLOW_DISPATCH_OUTBOX_ENABLED=False,
                    # Only the eval product routes to the Go gateway. The worker mints each
                    # run a capped scoped token with this key, as it does in production.
                    SANDBOX_AI_GATEWAY_PRODUCTS=EVAL_AI_PRODUCT,
                    SANDBOX_AI_GATEWAY_MINT_KEY=self._ai_gateway_mint_key,
                    **self.provider.settings_overrides(),
                )

            if overrides:
                stack.enter_context(override_settings(**overrides))
            stack.enter_context(
                patch.object(
                    posthoganalytics,
                    "feature_enabled",
                    partial(eval_feature_enabled, skill_delivery=self.options.skill_delivery),
                )
            )

            if Infra.SANDBOX in required:
                # Stale workflows from a prior run make the worker provision sandboxes for
                # runs that no longer exist, delaying the real eval workflows by 30-60s.
                await terminate_stale_workflows()

                worker = TemporalWorkerThread()
                worker.start()
                stack.callback(worker.stop)
                # A run interrupted before its own sweep leaves kernel rows behind in the
                # reused test database; reclaim those containers now rather than at the end.
                await self._sweep_notebook_kernels()
                stack.push_async_callback(self._sweep_notebook_kernels)

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
            if self._offline_delivery is not None:
                stack.push_async_callback(self._offline_delivery.pause)
            async with reporter.live_updates():
                results = await asyncio.gather(*(self._run_suite(suite, ctx) for suite in suites))
        return results

    async def _sweep_notebook_kernels(self) -> None:
        """Sweep every notebook kernel sandbox recorded in the eval database.

        A python or duckdb notebook cell provisions a kernel sandbox next to the case's
        agent sandbox, and docker ignores the sandbox TTL. Each case reclaims its own
        before it frees its slot; this catches whatever a crash or a timeout left behind.
        Registered on the stack that still holds the provider settings overrides, so the
        sandbox class resolves the same way it did when the kernel was created.
        """
        await reclaim_kernels(keep=self.provider is not None and self.provider.keeps_sandboxes())

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
            git_sha=self._git_sha,
            git_dirty=self._git_dirty,
            skills_sha256=self._skills_snapshot.sha256 if self._skills_snapshot is not None else None,
            skills_source_sha256=self._skills_snapshot.source_sha256 if self._skills_snapshot is not None else None,
            offline_delivery=self._offline_delivery,
            posthog_trace_host="https://us.posthog.com",
            posthog_trace_project_id=settings.LLM_ANALYTICS_INTERNAL_TEAM_ID,
            infrastructure_retries=self.options.infrastructure_retries,
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
