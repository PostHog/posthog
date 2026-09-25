from __future__ import annotations

import os
import sys
import json
import shlex
import hashlib
import logging
import argparse
import subprocess
from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from products.posthog_ai.eval_harness.harness.cli import HarnessOptions, parse_args
from products.posthog_ai.eval_harness.harness.django_env import setup_django
from products.posthog_ai.eval_harness.harness.env_preflight import load_env_file, validate_eval_env
from products.posthog_ai.eval_harness.harness.ports import LLM_GATEWAY_PORT, PERSONHOG_ROUTER_PORT
from products.posthog_ai.eval_harness.harness.providers import SANDBOX_PROVIDER_SETTING, PreflightError, build_provider
from products.posthog_ai.eval_harness.harness.transcript import RunTranscript

if TYPE_CHECKING:
    from products.posthog_ai.eval_harness.harness.context import EvalContext
    from products.signals.evals.agentic.retained_repository import RetainedScoutRepository
    from products.signals.evals.agentic.saved_case import SavedScoutCase

REPO_ROOT = Path(__file__).resolve().parents[3]
logger = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", force=True)
    logger.disabled = False
    for name in (
        "django_structlog.middlewares.request",
        "products.tasks.backend.logic.services.run_log_mirror",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)


def require_private_path(path: Path) -> Path:
    resolved = path.resolve()
    directory = resolved if resolved.is_dir() else resolved.parent
    while not directory.exists():
        directory = directory.parent
    repository = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=directory, check=False, capture_output=True, text=True
    )
    if repository.returncode == 0:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", str(resolved)],
            cwd=repository.stdout.strip(),
            check=False,
        )
        if result.returncode != 0:
            raise ValueError(f"Private case data and results must be outside Git or ignored: {resolved}")
    elif "not a git repository" not in repository.stderr:
        raise ValueError(f"Could not verify private storage for {resolved}: {repository.stderr.strip()}")
    return resolved


def parse_cutoff(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise argparse.ArgumentTypeError("The cutoff must include a timezone")
    return result.astimezone(UTC)


def preflight_saved_case(saved: SavedScoutCase, options: HarnessOptions) -> None:
    if saved.manifest.repository is not None and options.provider != "docker":
        raise PreflightError("Retained code repositories require --provider docker.")
    load_env_file()
    validate_eval_env(
        options.agent_runtime,
        env_hint=(
            f"Add them to {REPO_ROOT / '.env'} (loaded automatically by this saved-case command), "
            "or supply them explicitly through its launch environment. "
            "The command does not load .env.local; .codex/with-flox may discard ambient shell variables."
        ),
    )
    gateway_environment = REPO_ROOT / "services" / "llm-gateway" / ".venv"
    gateway_executable = gateway_environment / "bin" / "uvicorn"
    if not gateway_executable.is_file() or not os.access(gateway_executable, os.X_OK):
        raise PreflightError(
            f"The local LLM gateway executable is missing or not executable: {gateway_executable}. "
            "From this checkout's root, prepare its dependencies with "
            f"`.codex/with-flox env UV_PROJECT_ENVIRONMENT={shlex.quote(str(gateway_environment))} "
            "uv sync --project services/llm-gateway --frozen`."
        )
    build_provider(
        options.provider,
        keep_containers=options.keep_sandbox_containers,
        rebuild_image=options.rebuild_sandbox_image,
    ).preflight()


@asynccontextmanager
async def private_backend_gateway(ctx: EvalContext) -> AsyncIterator[None]:
    from django.conf import settings  # noqa: PLC0415 - CLI imports must remain Django-free.
    from django.test import override_settings  # noqa: PLC0415

    from posthog.models import PersonalAPIKey, User  # noqa: PLC0415
    from posthog.models.utils import generate_random_token_personal, hash_key_value  # noqa: PLC0415

    if not settings.TEST or ctx.demo_data is None:
        raise RuntimeError("Private backend model calls require the eval database and project setup")
    user = (
        await User.objects.filter(
            organization_membership__organization__team__id=ctx.demo_data.master_team_id,
            is_active=True,
        )
        .exclude(is_email_verified=False)
        .order_by("id")
        .afirst()
    )
    if user is None:
        raise RuntimeError("The eval master project has no eligible gateway user")
    token = generate_random_token_personal()
    key = await PersonalAPIKey.objects.acreate(
        user=user,
        label="Private saved scout gateway",
        secure_value=hash_key_value(token),
        scopes=["llm_gateway:read"],
        scoped_teams=[ctx.demo_data.master_team_id],
    )
    try:
        with override_settings(
            LLM_GATEWAY_URL=f"http://localhost:{LLM_GATEWAY_PORT}",
            LLM_GATEWAY_API_KEY=token,
            AI_GATEWAY_URL="",
            AI_GATEWAY_API_KEY="",
        ):
            yield
    finally:
        await key.adelete()


class SavedScoutSuite:
    def __init__(
        self,
        saved: SavedScoutCase,
        target_cutoff: datetime,
        output_dir: Path,
        retained: RetainedScoutRepository | None,
    ) -> None:
        self.saved = saved
        self.target_cutoff = target_cutoff
        self.output_dir = output_dir
        self.retained = retained

    async def run(self, ctx: EvalContext) -> None:
        from products.posthog_ai.eval_harness.base import (
            EvalTaskError,  # noqa: PLC0415 — Django must be initialized first
        )
        from products.posthog_ai.eval_harness.config import (
            SandboxedEvalCase,  # noqa: PLC0415 — Django must be initialized first
        )
        from products.posthog_ai.eval_harness.engines.types import CaseHooks  # noqa: PLC0415
        from products.posthog_ai.eval_harness.workflow import WorkflowPrivateEval  # noqa: PLC0415
        from products.signals.evals.agentic.runners import run_scout  # noqa: PLC0415
        from products.tasks.backend.facade.agents import CustomPromptSandboxContext  # noqa: PLC0415

        scout_case = self.saved.to_scout_case(self.target_cutoff)

        async def task(
            case: SandboxedEvalCase,
            context: CustomPromptSandboxContext,
            eval_context: EvalContext,
            hooks: CaseHooks,
        ) -> dict[str, object]:
            hooks.metadata.update(self.saved.metadata)
            hooks.metadata["target_cutoff"] = self.target_cutoff.isoformat()
            output = await run_scout(scout_case, context, eval_context)
            if not output.get("run_id") or not output.get("task_run_id") or not output.get("raw_log"):
                raise EvalTaskError("The scout did not produce an agent run and transcript", output)
            task_run = output.get("artifacts", {}).get("task_run", {})
            if task_run.get("status") != "completed":
                raise EvalTaskError(f"The scout task did not complete: {task_run.get('status')}", output)
            output["exit_code"] = 0
            if self.retained is not None:
                output.setdefault("artifacts", {})["repository"] = {
                    **self.retained.metadata,
                    "verified_sandboxes": self.retained.verified_sandboxes,
                }
            return output

        async with private_backend_gateway(ctx):
            result = await WorkflowPrivateEval(
                experiment_name="signals-saved-scout",
                cases=[
                    SandboxedEvalCase(
                        name=scout_case.case_id,
                        prompt=f"Scout run: {scout_case.skill_name}",
                        project_data="empty",
                        metadata=self.saved.metadata,
                        setup=lambda context: self.saved.restore(context, target_cutoff=self.target_cutoff),
                    )
                ],
                scorers=[],
                task=task,
                ctx=ctx,
                output_dir=self.output_dir,
            )
        if not result.results or any(row.error or (row.output or {}).get("error") for row in result.results):
            raise RuntimeError("A saved scout run failed; inspect the private output directory")


def run_saved_case(saved: SavedScoutCase, options: HarnessOptions, target_cutoff: datetime, output_dir: Path) -> int:
    preflight_saved_case(saved, options)
    os.environ.update(
        SANDBOX_PROVIDER=SANDBOX_PROVIDER_SETTING[options.provider],
        PERSONHOG_ADDR=f"127.0.0.1:{PERSONHOG_ROUTER_PORT}",
        OPT_OUT_CAPTURE="1",
        LLM_GATEWAY_POSTHOG_AI_LANE_CAPTURE="false",
        LLM_GATEWAY_POSTHOG_PROJECT_TOKEN="",
        LLM_GATEWAY_POSTHOG_SECONDARY_PROJECT_TOKEN="",
    )
    setup_django()

    from products.posthog_ai.eval_harness.engines.braintrust import (
        PrivateBraintrustEngine,  # noqa: PLC0415 — Django must be initialized first
    )
    from products.posthog_ai.eval_harness.harness.discovery import EvalSuite  # noqa: PLC0415
    from products.posthog_ai.eval_harness.harness.lifecycle import SandboxedEvalHarness  # noqa: PLC0415
    from products.signals.evals.agentic.retained_repository import RetainedScoutRepository  # noqa: PLC0415

    configure_logging()

    with ExitStack() as stack:
        retained = None
        if repository := saved.manifest.repository:
            source = Path(repository.source_path)
            if not source.is_absolute():
                source = saved.path.parent / source
            logger.info("Preparing retained repository at %s", repository.commit)
            retained = stack.enter_context(
                RetainedScoutRepository(
                    source,
                    repository.commit,
                    repository=repository.name,
                    history_depth=repository.history_depth,
                    cache_directory=output_dir.parent.parent
                    / "repositories"
                    / f"{repository.commit}-{repository.history_depth or 'full'}",
                )
            )
        suite = SavedScoutSuite(saved, target_cutoff, output_dir, retained)
        return SandboxedEvalHarness(
            options,
            engine=PrivateBraintrustEngine(),
            suites=[EvalSuite("signals", "saved_scout", "saved_scout", suite.run)],
        ).run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a private saved scout case through the shared eval harness",
        epilog=(
            "Also accepts shared harness options: --provider, --agent-runtime, --agent-model, "
            "--reasoning-effort, --trials, --case-timeout, --max-sandboxes, and --skill-delivery."
        ),
    )
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--target-cutoff", required=True, type=parse_cutoff)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--validate-only", action="store_true", help="Validate saved inputs without checking execution prerequisites."
    )
    mode.add_argument(
        "--preflight-only",
        action="store_true",
        help="Validate saved inputs and local execution prerequisites without starting services or an agent.",
    )
    args, harness_args = parser.parse_known_args(argv)
    options = parse_args(harness_args)

    from products.signals.evals.agentic.saved_case import (
        SavedScoutCase,  # noqa: PLC0415 — validation is optional for --help
    )

    os.umask(0o077)
    case_path = require_private_path(args.case)
    output_dir = require_private_path(args.output_dir)
    saved = SavedScoutCase.load(case_path)
    if args.validate_only:
        print(json.dumps(saved.metadata, indent=2, default=str))  # noqa: T201
        return 0
    if args.preflight_only:
        try:
            preflight_saved_case(saved, options)
        except PreflightError as error:
            parser.error(str(error))
        print(  # noqa: T201
            "Saved scout preflight passed. This does not verify model authentication, databases, "
            "service ports, repository bundles, or sandbox images."
        )
        return 0
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    transcript = RunTranscript.create(output_dir / "harness")
    invocation_dir = output_dir / "invocations" / transcript.path.stem
    invocation_dir.mkdir(parents=True, mode=0o700)
    patch = subprocess.run(["git", "diff", "HEAD", "--binary"], cwd=REPO_ROOT, check=True, capture_output=True).stdout
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    (invocation_dir / "source.patch").write_bytes(patch)
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split("\0")
    source_files: dict[str, str] = {}
    for name in filter(None, untracked):
        source = REPO_ROOT / name
        if source.is_file():
            content = source.read_bytes()
            target = invocation_dir / "source-files" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            source_files[name] = hashlib.sha256(content).hexdigest()
    history = {
        "started_at": datetime.now(UTC).isoformat(),
        "case_path": str(case_path),
        "case_sha256": hashlib.sha256(case_path.read_bytes()).hexdigest(),
        "skill_sha256": saved.manifest.skill.body.sha256,
        "case": saved.metadata,
        "source_commit": commit,
        "source_patch_sha256": hashlib.sha256(patch).hexdigest(),
        "untracked_source_files": source_files,
        "target_cutoff": args.target_cutoff.isoformat(),
        "agent_runtime": options.agent_runtime,
        "agent_model": options.agent_model,
        "reasoning_effort": options.reasoning_effort,
        "trials": options.trials,
        "provider": options.provider,
        "arguments": list(argv if argv is not None else sys.argv[1:]),
        "transcript": str(transcript.path),
    }
    history_path = invocation_dir / "invocation.json"
    history_path.write_text(json.dumps(history, indent=2, default=str) + "\n")
    exit_code = 1
    try:
        with transcript.capture():
            configure_logging()
            try:
                exit_code = run_saved_case(saved, options, args.target_cutoff, invocation_dir)
            except KeyboardInterrupt:
                logger.warning("Interrupted")
                exit_code = 130
            except Exception:
                configure_logging()
                logger.exception("Saved scout run failed")
            finally:
                logging.shutdown()
    finally:
        history.update(finished_at=datetime.now(UTC).isoformat(), exit_code=exit_code)
        history_path.write_text(json.dumps(history, indent=2, default=str) + "\n")
        transcript.finish()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
