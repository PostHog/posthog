from __future__ import annotations

import os
import sys
import json
import hashlib
import logging
import argparse
import subprocess
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

from products.posthog_ai.eval_harness.harness.cli import HarnessOptions, parse_args
from products.posthog_ai.eval_harness.harness.django_env import setup_django
from products.posthog_ai.eval_harness.harness.ports import PERSONHOG_ROUTER_PORT
from products.posthog_ai.eval_harness.harness.providers import SANDBOX_PROVIDER_SETTING
from products.posthog_ai.eval_harness.harness.transcript import RunTranscript
from products.signals.evals.agentic.rubric_judge import DEFAULT_GENERATOR_MODEL
from products.signals.evals.agentic.saved_case import SavedFile, SavedScoutCase
from products.signals.evals.agentic.saved_comparison_plan import SavedComparisonPlan
from products.signals.evals.saved_scout import (
    REPO_ROOT,
    configure_logging,
    parse_cutoff,
    preflight_saved_case,
    require_private_path,
)

logger = logging.getLogger(__name__)


def snapshot_plan(plan: SavedComparisonPlan, source_directory: Path, output_path: Path) -> SavedComparisonPlan:
    comparisons = []
    for comparison in plan.comparisons:
        variants = []
        for variant in comparison.variants:
            if variant.instructions is not None:
                content = variant.instructions.resolve(source_directory).read_bytes()
                filename = f"variant-{hashlib.sha256(content).hexdigest()}.md"
                (output_path.parent / filename).write_bytes(content)
                variant = variant.model_copy(
                    update={"instructions": SavedFile(path=filename, sha256=hashlib.sha256(content).hexdigest())}
                )
            variants.append(variant)
        comparisons.append(comparison.model_copy(update={"variants": tuple(variants)}))
    snapshot = plan.model_copy(update={"comparisons": tuple(comparisons)})
    output_path.write_text(snapshot.model_dump_json(indent=2) + "\n")
    return snapshot


def run_comparisons(
    cases: tuple[SavedScoutCase, ...],
    plan: SavedComparisonPlan,
    plan_path: Path,
    options: HarnessOptions,
    target_cutoff: datetime,
    session_dir: Path,
    invocation_dir: Path,
    rubric_model: str,
) -> int:
    for saved in cases:
        preflight_saved_case(saved, options)
    os.environ.update(
        SANDBOX_PROVIDER=SANDBOX_PROVIDER_SETTING[options.provider],
        PERSONHOG_ADDR=f"127.0.0.1:{PERSONHOG_ROUTER_PORT}",
        OPT_OUT_CAPTURE="1",
        SCOUT_LIVE_TRIALS_ENABLED="true",
        SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE="true",
        LLM_GATEWAY_POSTHOG_AI_LANE_CAPTURE="false",
        LLM_GATEWAY_POSTHOG_PROJECT_TOKEN="",
        LLM_GATEWAY_POSTHOG_SECONDARY_PROJECT_TOKEN="",
        POSTHOG_ANALYTICS_API_KEY="",
        POSTHOG_ANALYTICS_HOST="",
    )
    setup_django()
    configure_logging()
    logger.disabled = False

    from products.posthog_ai.eval_harness.engines.braintrust import (
        PrivateBraintrustEngine,  # noqa: PLC0415 — initialize Django first
    )
    from products.posthog_ai.eval_harness.harness.discovery import EvalSuite  # noqa: PLC0415
    from products.posthog_ai.eval_harness.harness.lifecycle import SandboxedEvalHarness  # noqa: PLC0415
    from products.signals.evals.agentic.retained_repository import RetainedScoutRepository  # noqa: PLC0415
    from products.signals.evals.agentic.saved_comparison import (  # noqa: PLC0415
        SavedComparisonSuite,
        write_private_json,
    )
    from products.signals.evals.agentic.saved_dataset import SavedScoutDataset  # noqa: PLC0415

    dataset = SavedScoutDataset.prepare(cases, invocation_dir / "dataset")
    with ExitStack() as stack:
        retained_fixture: RetainedScoutRepository | None = None
        retained = next((saved for saved in cases if saved.manifest.repository is not None), None)
        if retained is not None:
            repository = retained.manifest.repository
            assert repository is not None
            source = Path(repository.source_path)
            if not source.is_absolute():
                source = retained.path.parent / source
            retained_fixture = stack.enter_context(
                RetainedScoutRepository(
                    source,
                    repository.commit,
                    repository=repository.name,
                    history_depth=repository.history_depth,
                    cache_directory=session_dir
                    / "repositories"
                    / f"{repository.commit}-{repository.history_depth or 'full'}",
                )
            )
        suite = SavedComparisonSuite(
            dataset, plan, plan_path.parent, target_cutoff, session_dir, invocation_dir, rubric_model
        )
        try:
            return SandboxedEvalHarness(
                options,
                engine=PrivateBraintrustEngine(),
                suites=[EvalSuite("signals", "saved_comparison", "saved_comparison", suite.run)],
            ).run()
        finally:
            if retained_fixture is not None:
                write_private_json(
                    invocation_dir / "repository.json",
                    {**retained_fixture.metadata, "verified_sandboxes": retained_fixture.verified_sandboxes},
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run online scout comparisons against a private restored Parquet dataset"
    )
    parser.add_argument(
        "--case", action="append", required=True, type=Path, help="Repeat to restore several scouts together"
    )
    parser.add_argument(
        "--plan", required=True, type=Path, help="Private JSON config naming scouts, variants and repeats"
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--session-dir", type=Path, help="Reuse frozen rubrics across invocations; defaults to --output-dir"
    )
    parser.add_argument("--target-cutoff", required=True, type=parse_cutoff)
    parser.add_argument("--rubric-model", default=DEFAULT_GENERATOR_MODEL)
    parser.add_argument("--validate-only", action="store_true")
    args, harness_args = parser.parse_known_args(argv)
    options = parse_args(harness_args)
    if options.trials != 1:
        parser.error(
            "Set repeats in the comparison plan; --trials must remain 1 so all runs share one restored dataset"
        )
    if options.provider != "docker":
        parser.error("Saved online comparisons currently require the local Docker provider")
    if options.selectors or options.case_filter or options.list_only or options.fail_under is not None:
        parser.error("Select scouts in --plan; use the online comparison report for scoring")
    os.umask(0o077)
    cases = tuple(SavedScoutCase.load(require_private_path(path)) for path in args.case)
    plan_path = require_private_path(args.plan).resolve(strict=True)
    plan = SavedComparisonPlan.model_validate_json(plan_path.read_text())
    plan.validate_inputs(plan_path.parent, cases, options.max_sandboxes, target_cutoff=args.target_cutoff)
    repositories = {saved.manifest.repository.model_dump_json() for saved in cases if saved.manifest.repository}
    if len(repositories) > 1:
        parser.error("A comparison batch must use one retained repository snapshot")
    output_dir = require_private_path(args.output_dir)
    session_dir = require_private_path(args.session_dir or args.output_dir)
    if args.validate_only:
        from tempfile import TemporaryDirectory  # noqa: PLC0415 — validation prepares no services

        from products.signals.evals.agentic.saved_dataset import SavedScoutDataset  # noqa: PLC0415

        with TemporaryDirectory(prefix="scout-dataset-validation-") as directory:
            dataset = SavedScoutDataset.prepare(cases, Path(directory) / "dataset")
            print(json.dumps(dataset.metadata, indent=2))  # noqa: T201
        return 0
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    transcript = RunTranscript.create(output_dir / "harness")
    invocation_dir = output_dir / "invocations" / transcript.path.stem
    invocation_dir.mkdir(parents=True, mode=0o700)
    original_plan_directory = plan_path.parent
    plan_path = invocation_dir / "comparison-plan.json"
    plan = snapshot_plan(plan, original_plan_directory, plan_path)
    source_patch = subprocess.run(
        ["git", "diff", "HEAD", "--binary"], cwd=REPO_ROOT, check=True, capture_output=True
    ).stdout
    (invocation_dir / "source.patch").write_bytes(source_patch)
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
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    history = {
        "started_at": datetime.now(UTC).isoformat(),
        "source_commit": source_commit,
        "source_patch_sha256": hashlib.sha256(source_patch).hexdigest(),
        "untracked_source_files": source_files,
        "cases": [saved.metadata for saved in cases],
        "target_cutoff": args.target_cutoff.isoformat(),
        "session_dir": str(session_dir),
        "judge_policy": "online evidence limits; full logs exported separately",
        "arguments": list(argv if argv is not None else sys.argv[1:]),
    }
    history_path = invocation_dir / "invocation.json"
    history_path.write_text(json.dumps(history, indent=2) + "\n")
    exit_code = 1
    try:
        with transcript.capture():
            configure_logging()
            try:
                exit_code = run_comparisons(
                    cases, plan, plan_path, options, args.target_cutoff, session_dir, invocation_dir, args.rubric_model
                )
            except KeyboardInterrupt:
                logger.warning("Interrupted")
                exit_code = 130
            except Exception:
                logger.exception("Saved comparison failed")
            finally:
                logging.shutdown()
    finally:
        history.update(finished_at=datetime.now(UTC).isoformat(), exit_code=exit_code)
        history_path.write_text(json.dumps(history, indent=2) + "\n")
        transcript.finish()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
