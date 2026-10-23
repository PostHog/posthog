# ruff: noqa: T201
from __future__ import annotations

import os
import sys
import json
import argparse
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from pydantic import TypeAdapter, ValidationError

from products.posthog_ai.eval_harness.environment.cli import load_backend, parse_cutoff
from products.posthog_ai.eval_harness.environment.dataset import EnvironmentDataset
from products.posthog_ai.eval_harness.environment.storage import file_sha256, require_private_path, workspace_lock
from products.posthog_ai.eval_harness.environment.transform import EnvironmentTransform
from products.signals.backend.scout_harness.eval_environment.prompt import NativeScoutPrompt, RecordedScoutPrompt
from products.signals.backend.scout_harness.eval_environment.recipes import EventRecipe
from products.signals.backend.scout_harness.eval_environment.schema import ScoutEnvironmentCase, ScoutEnvironmentSeed
from products.signals.backend.scout_harness.eval_environment.traces import load_trace_inputs
from products.signals.backend.scout_harness.eval_environment.trials import (
    BudgetLedger,
    EvaluationPlan,
    FrozenEnvironment,
    ScoutEvaluationTrials,
    TrialVariant,
    write_private_json,
)
from products.signals.backend.scout_harness.prompt import HARNESS_PROMPT_VERSION

if TYPE_CHECKING:
    from products.posthog_ai.eval_harness.environment.restore import EnvironmentReceipt


class ScoutEnvironmentCommand:
    def __init__(self, workspace: Path) -> None:
        self.workspace = require_private_path(workspace)

    @staticmethod
    def default_cutoff(source_cutoff: datetime, now: datetime) -> datetime:
        delta = now - source_cutoff
        return now - timedelta(microseconds=delta.microseconds)

    def prepare(self, case_path: Path, bundle: Path, *, cutoff: datetime | None, user_id: int | None) -> None:
        case_path = require_private_path(case_path)
        case = ScoutEnvironmentCase.model_validate_json(case_path.read_bytes())
        bundle = require_private_path(bundle)
        dataset = EnvironmentDataset.load(bundle / "environment.json")
        if (
            dataset.manifest.environment_id != case.environment_id
            or dataset.manifest.source_cutoff != case.source_cutoff
        ):
            raise ValueError("The case and event bundle describe different environments.")
        backend = load_backend()
        if cutoff is None and backend.read_receipt(self.workspace) is None:
            cutoff = self.default_cutoff(case.source_cutoff, datetime.now(UTC))
        from products.signals.backend.scout_harness.eval_environment.ingestion import (  # noqa: PLC0415
            ScoutEnvironmentIngestion,
        )
        from products.signals.backend.scout_harness.eval_environment.state import ScoutEnvironmentState  # noqa: PLC0415

        with workspace_lock(self.workspace):
            result = backend.restore(dataset, workspace=self.workspace, target_cutoff=cutoff, user_id=user_id)
            receipt = backend.read_receipt(self.workspace)
            if receipt is None:
                raise ValueError("The restored environment has no receipt.")
            ScoutEnvironmentIngestion.prepare(receipt)
            seed_path = self.workspace / "scout-seed.json"
            if seed_path.exists():
                seed = ScoutEnvironmentSeed.model_validate_json(seed_path.read_bytes())
                if seed.team_id != result.team_id or seed.environment_id != case.environment_id:
                    raise ValueError("The saved scout seed belongs to another environment.")
            else:
                # Commit the seeded rows only once the seed receipt exists, so a failed write can be retried.
                with transaction.atomic():
                    seed = ScoutEnvironmentState.seed(case, receipt)
                    write_private_json(seed_path, seed)
            print(json.dumps({"team_id": seed.team_id, "config_id": str(seed.config_id), "paid_calls": 0}))

    def freeze(self, case_path: Path, bundle: Path, *, extra_inputs: list[Path] | None = None) -> None:
        case_path = require_private_path(case_path)
        case = ScoutEnvironmentCase.model_validate_json(case_path.read_bytes())
        dataset = EnvironmentDataset.load(require_private_path(bundle) / "environment.json")
        dataset.validate_files()
        backend = load_backend()
        receipt = backend.read_receipt(self.workspace)
        if receipt is None or receipt.phase != "complete":
            raise ValueError("Prepare the environment successfully before freezing it.")
        seed_path = self.workspace / "scout-seed.json"
        seed = ScoutEnvironmentSeed.model_validate_json(seed_path.read_bytes())
        if (
            receipt.manifest_sha256 != dataset.manifest_sha256
            or receipt.environment_id != case.environment_id
            or dataset.manifest.environment_id != case.environment_id
            or seed.environment_id != case.environment_id
            or seed.team_id != receipt.team_id
        ):
            raise ValueError(
                "The case, event bundle, seed and receipt describe different environments. "
                "Prepare the changed inputs in a new workspace."
            )
        paths = [case_path, self.workspace / "receipt.json", seed_path, dataset.path]
        paths.extend(reference.resolve(dataset.path.parent) for reference in dataset.manifest.events)
        if dataset.manifest.metrics:
            paths.append(dataset.manifest.metrics.resolve(dataset.path.parent))
        paths.extend(require_private_path(path) for path in extra_inputs or [])
        inputs = {str(require_private_path(path)): file_sha256(path) for path in paths}
        freeze_path = self.workspace / "frozen.json"
        if freeze_path.exists():
            previous = FrozenEnvironment.model_validate_json(freeze_path.read_bytes())
            previous.verify()
            previous.verify_case(case)
            if previous.inputs != inputs:
                raise ValueError("This reconstruction was frozen with other inputs. Use a new workspace.")
        else:
            prompt_path = self.workspace / "runtime-prompt.json"
            prompt = self._prompt(case, seed, receipt, inputs)
            write_private_json(prompt_path, prompt)
            document = FrozenEnvironment.create(paths, seed, runtime_prompt=prompt_path, case=case)
            write_private_json(freeze_path, document)
        print(json.dumps({"frozen_sha256": file_sha256(freeze_path), "paid_calls": 0}))

    def _prompt(
        self,
        case: ScoutEnvironmentCase,
        seed: ScoutEnvironmentSeed,
        receipt: EnvironmentReceipt,
        frozen_inputs: dict[str, str],
    ) -> RecordedScoutPrompt | NativeScoutPrompt:
        if case.prompt_mode == "native":
            if HARNESS_PROMPT_VERSION == "unknown" or (
                case.expected_harness_prompt_version is not None
                and case.expected_harness_prompt_version != HARNESS_PROMPT_VERSION
            ):
                raise ValueError("The native case requires a known, matching local harness prompt version.")
            return NativeScoutPrompt(
                team_id=seed.team_id,
                config_id=seed.config_id,
                skill_name=case.skill.name,
                skill_version=case.skill.version,
                allowed_tools=case.skill.allowed_tools,
                harness_prompt_version=HARNESS_PROMPT_VERSION,
                frozen_inputs=frozen_inputs,
                frozen_manifest=str(self.workspace / "frozen.json"),
            )
        if not case.recorded_prompt or not case.expected_harness_prompt_version:
            raise ValueError("Preserve the full recorded scout prompt and its harness version before freezing.")
        transform = EnvironmentTransform(
            source_cutoff=case.source_cutoff,
            target_cutoff=receipt.target_cutoff,
            namespace=receipt.identity_namespace,
            record_ids=[],
            time_strings=case.time_strings,
            string_replacements=case.string_replacements,
            source_project_url=case.source_project_url,
            target_project_url=receipt.target_project_url,
        )
        replacements = {**seed.identity_map, **case.string_replacements}
        for value in case.time_strings:
            shifted = transform.value(value)
            if not isinstance(shifted, str):
                raise ValueError("Declared prompt time strings must transform to strings.")
            replacements[value] = shifted
        return RecordedScoutPrompt(
            team_id=seed.team_id,
            config_id=seed.config_id,
            skill_name=case.skill.name,
            skill_version=case.skill.version,
            allowed_tools=case.skill.allowed_tools,
            recorded_prompt=case.recorded_prompt,
            prompt_transformations=case.prompt_transformations,
            harness_prompt_version=case.expected_harness_prompt_version,
            replacements=replacements,
            time_strings=case.time_strings,
            frozen_inputs=frozen_inputs,
            frozen_manifest=str(self.workspace / "frozen.json"),
            source_project_url=case.source_project_url,
            target_project_url=receipt.target_project_url,
        )

    def trials(self, case_path: Path) -> ScoutEvaluationTrials:
        load_backend()
        return ScoutEvaluationTrials(
            ScoutEnvironmentCase.model_validate_json(require_private_path(case_path).read_bytes()),
            ScoutEnvironmentSeed.model_validate_json((self.workspace / "scout-seed.json").read_bytes()),
            self.workspace / "frozen.json",
        )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state-dir", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "freeze", "check", "run", "export"):
        command = commands.add_parser(name)
        command.add_argument("--case", type=Path, required=True)
        if name in {"prepare", "freeze"}:
            command.add_argument("--bundle", type=Path, required=True)
        if name == "freeze":
            command.add_argument(
                "--extra-input",
                type=Path,
                action="append",
                default=[],
                help="Private recipe, builder, assumptions or supplemental receipt to bind; repeat for each file",
            )
        if name == "prepare":
            command.add_argument("--target-cutoff", type=parse_cutoff)
            command.add_argument("--user-id", type=int)
        if name == "check":
            command.add_argument(
                "--probe", action="store_true", help="Mint and revoke a local gateway token without model calls"
            )
        if name in {"run", "export"}:
            command.add_argument("--plan", type=Path, required=True)
        if name == "run":
            command.add_argument("--variants", type=Path, help="Private JSON list; default is exactly one scout run")
            command.add_argument(
                "--ledger", type=Path, required=True, help="One shared budget file for the whole campaign"
            )
            command.add_argument(
                "--launch", action="store_true", help="Start the saved paid plan; otherwise only prepare it"
            )
        if name == "export":
            command.add_argument("--output", type=Path, required=True)
    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("--ledger", type=Path, required=True)
    reconcile.add_argument("--comparison-id", type=UUID, required=True)
    reconcile.add_argument("--actual-usd", type=Decimal, required=True)
    extract = commands.add_parser("extract")
    extract.add_argument("--run", type=Path, required=True, help="Private run directory with raw paginated logs")
    extract.add_argument(
        "--read-tools", type=Path, required=True, help="Private JSON list of permitted read tool names"
    )
    extract.add_argument(
        "--output", type=Path, required=True, help="Private observations file outside the scout bundle"
    )
    events = commands.add_parser("build-events")
    events.add_argument("--recipe", type=Path, required=True, help="Private JSON event reconstruction recipe")
    events.add_argument("--output", type=Path, required=True, help="New private Parquet events file; never overwritten")


def execute(args: argparse.Namespace) -> int:
    os.umask(0o077)
    try:
        command = ScoutEnvironmentCommand(args.state_dir)
        if args.command == "build-events":
            recipe = EventRecipe.model_validate_json(require_private_path(args.recipe).read_bytes())
            output = require_private_path(args.output)
            recipe.write_events(output)
            print(json.dumps({"output": str(output), "paid_calls": 0}))
        elif args.command == "extract":
            read_tools = TypeAdapter(list[str]).validate_json(require_private_path(args.read_tools).read_bytes())
            inputs = load_trace_inputs(require_private_path(args.run), read_tools=read_tools)
            write_private_json(
                require_private_path(args.output),
                {
                    "observations": [
                        {
                            "event_index": observation.event_index,
                            "timestamp": observation.timestamp.isoformat(),
                            "tool": observation.tool,
                            "arguments": observation.arguments,
                            "text": observation.text,
                        }
                        for observation in inputs.observations
                    ],
                    "local_file_reads": [
                        {
                            "event_index": observation.event_index,
                            "timestamp": observation.timestamp.isoformat(),
                            "tool": observation.tool,
                            "arguments": observation.arguments,
                            "text": observation.text,
                        }
                        for observation in inputs.local_file_reads
                    ],
                    "first_write_index": inputs.first_write_index,
                },
            )
            print(
                json.dumps(
                    {
                        "read_observations": len(inputs.observations),
                        "local_file_reads": len(inputs.local_file_reads),
                        "paid_calls": 0,
                    }
                )
            )
        elif args.command == "prepare":
            command.prepare(args.case, args.bundle, cutoff=args.target_cutoff, user_id=args.user_id)
        elif args.command == "freeze":
            command.freeze(args.case, args.bundle, extra_inputs=args.extra_input)
        elif args.command == "reconcile":
            budget = BudgetLedger(args.ledger).settle(args.comparison_id, args.actual_usd)
            print(json.dumps({"committed_usd": str(budget.committed_usd), "limit_usd": str(budget.limit_usd)}))
        else:
            trials = command.trials(args.case)
            if args.command == "check":
                print(json.dumps(trials.check(probe_gateway=args.probe)))
            elif args.command == "export":
                plan = EvaluationPlan.model_validate_json(require_private_path(args.plan).read_bytes())
                print(json.dumps(trials.export(plan, require_private_path(args.output))))
            else:
                plan_path = require_private_path(args.plan)
                if args.launch:
                    plan = EvaluationPlan.model_validate_json(plan_path.read_bytes())
                    print(json.dumps({"workflow_id": trials.launch(plan, BudgetLedger(args.ledger))}))
                else:
                    if plan_path.exists():
                        raise ValueError(
                            "The trial plan already exists. Launch or export it; do not overwrite its IDs."
                        )
                    if args.variants:
                        variants = TypeAdapter(list[TrialVariant]).validate_json(
                            require_private_path(args.variants).read_bytes()
                        )
                    else:
                        model = trials.case.config.get("model")
                        effort = trials.case.config.get("reasoning_effort")
                        if not isinstance(model, str) or not model or not isinstance(effort, str) or not effort:
                            raise ValueError(
                                "Preserve the source model and reasoning effort or provide explicit --variants."
                            )
                        variants = [TrialVariant(label="baseline", model=model, reasoning_effort=effort)]
                    plan = trials.plan(variants)
                    write_private_json(plan_path, plan)
                    print(json.dumps({"mode": plan.mode, "reserved_usd": str(plan.reserved_usd), "paid_calls": 0}))
    except (ValidationError, DjangoValidationError):
        print("Scout environment input validation failed; private field values were not printed.", file=sys.stderr)
        return 1
    except (ValueError, OSError, RuntimeError) as error:
        print(f"Scout environment command failed: {error}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconstruct and evaluate a private scout case against local PostHog.")
    add_arguments(parser)
    return execute(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
