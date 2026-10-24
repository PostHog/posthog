import os
import json
import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Literal
from uuid import uuid4

from unittest import TestCase
from unittest.mock import patch

from django.core.exceptions import ValidationError as DjangoValidationError

from parameterized import parameterized
from pydantic import ValidationError

from products.posthog_ai.eval_harness.environment.dataset import EnvironmentDataset
from products.posthog_ai.eval_harness.environment.storage import file_sha256
from products.posthog_ai.eval_harness.environment.transform import EnvironmentTransform
from products.signals.backend.scout_harness.eval_environment.cli import (
    ScoutEnvironmentCommand,
    add_arguments,
    execute,
    main,
)
from products.signals.backend.scout_harness.eval_environment.prompt import (
    RecordedScoutPrompt,
    read_native_prompt,
    read_recorded_prompt,
)
from products.signals.backend.scout_harness.eval_environment.schema import (
    ScoutEnvironmentCase,
    ScoutEnvironmentSeed,
    ScoutEnvironmentSkill,
)
from products.signals.backend.scout_harness.eval_environment.support import ScoutEnvironmentSupport
from products.signals.backend.scout_harness.eval_environment.trials import (
    EvaluationPlan,
    FrozenEnvironment,
    write_private_json,
)
from products.signals.backend.scout_harness.trial_comparison_types import TrialComparisonRequest, TrialComparisonVariant


class TestScoutEvaluationFreeze(TestCase):
    @parameterized.expand(
        [
            "shared_legacy_claim",
            "wrong_report",
            "wrong_artefact_type",
            "duplicate_assignment",
            "duplicate_artefact",
            "other_record",
            "skill",
        ]
    )
    def test_record_ids_only_overlap_for_a_legacy_assignment_and_its_report_work_claim(self, change: str) -> None:
        cutoff = datetime(2030, 1, 1, tzinfo=UTC)
        report_id, claim_id = uuid4(), uuid4()
        artefact: dict[str, object] = {
            "id": claim_id,
            "created_at": cutoff,
            "fields": {"report_id": str(report_id), "type": "work_claim", "content": "{}"},
        }
        assignment: dict[str, object] = {
            "id": claim_id,
            "created_at": cutoff,
            "fields": {"report_id": str(report_id)},
        }
        state: dict[str, list[dict[str, object]]] = {
            "reports": [{"id": report_id, "created_at": cutoff, "fields": {"title": "Example report"}}],
            "report_artefacts": [artefact],
            "report_assignments": [assignment],
        }
        if change == "wrong_report":
            assignment["fields"] = {"report_id": str(uuid4())}
        elif change == "wrong_artefact_type":
            artefact["fields"] = {"report_id": str(report_id), "type": "note", "content": "{}"}
        elif change == "duplicate_assignment":
            state["report_assignments"].append(assignment)
        elif change == "duplicate_artefact":
            state["report_artefacts"].append(artefact)
        elif change == "other_record":
            state["notes"] = [{"id": claim_id, "created_at": cutoff, "fields": {"content": "Example note"}}]
        data = {
            "environment_id": "example",
            "source_cutoff": cutoff,
            "checkpoint": cutoff,
            "skill": {
                "id": claim_id if change == "skill" else uuid4(),
                "name": "example-scout",
                "body": "Review example events.",
                "version": 1,
                "origin": "custom",
            },
            "state": state,
        }
        if change == "shared_legacy_claim":
            case = ScoutEnvironmentCase.model_validate(data)
            ScoutEnvironmentSupport.validate(case)
            self.assertEqual(case.state.report_artefacts[0].id, case.state.report_assignments[0].id)
        else:
            with self.assertRaisesRegex(ValidationError, "Starting-state record IDs must be unique"):
                ScoutEnvironmentCase.model_validate(data)

    @parameterized.expand(
        [(mode, change) for mode in ("recorded", "native") for change in ("unchanged", "removed", "added", "modified")]
    )
    def test_freeze_binds_extra_inputs_and_requires_the_same_inputs_on_reuse(
        self, mode: Literal["recorded", "native"], change: str
    ) -> None:
        self.addCleanup(os.umask, os.umask(0o077))
        with TemporaryDirectory() as folder:
            directory = Path(folder).resolve()
            workspace = directory / "state"
            cutoff = datetime(2030, 1, 1, tzinfo=UTC)
            dataset = EnvironmentDataset.build(
                directory / "bundle", environment_id="example", event_paths=[], source_cutoff=cutoff
            )
            case = ScoutEnvironmentCase(
                environment_id="example",
                source_cutoff=cutoff,
                checkpoint=cutoff,
                skill=ScoutEnvironmentSkill(
                    id=uuid4(), name="example-scout", body="Review example events.", version=1, origin="custom"
                ),
                prompt_mode=mode,
                recorded_prompt=(
                    "- **team_id**: `2`\n- **run_id**: `source-run`\n"
                    "- **started_at**: `2030-01-01T00:00:00Z`\n<run_note>\nReview example events.\n</run_note>"
                )
                if mode == "recorded"
                else "",
                expected_harness_prompt_version="example-version" if mode == "recorded" else None,
            )
            case_path = directory / "case.json"
            write_private_json(case_path, case)
            seed = ScoutEnvironmentSeed(
                environment_id=case.environment_id,
                team_id=7,
                user_id=7,
                config_id=uuid4(),
                skill_id=case.skill.id,
                identity_map={},
                time_delta_seconds=0,
                steering=case.steering,
            )
            write_private_json(workspace / "scout-seed.json", seed)
            write_private_json(workspace / "receipt.json", {"phase": "complete"})
            extra_inputs = [directory / "recipe.json", directory / "builder.py", directory / "assumptions.md"]
            for path in extra_inputs:
                path.write_text("Invented reconstruction input.\n")
            arguments = [
                "--state-dir",
                str(workspace),
                "freeze",
                "--case",
                str(case_path),
                "--bundle",
                str(dataset.path.parent),
            ]

            def freeze(paths: list[Path]) -> int:
                return main([*arguments, *(argument for path in paths for argument in ("--extra-input", str(path)))])

            with (
                patch("products.signals.backend.scout_harness.eval_environment.cli.load_backend") as load_backend,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                load_backend.return_value.read_receipt.return_value = SimpleNamespace(
                    phase="complete",
                    target_cutoff=cutoff,
                    identity_namespace=uuid4(),
                    manifest_sha256=dataset.manifest_sha256,
                    environment_id=case.environment_id,
                    team_id=seed.team_id,
                    target_project_url=None,
                )
                assert freeze(extra_inputs) == 0
                frozen_path = workspace / "frozen.json"
                prompt_path = workspace / "runtime-prompt.json"
                frozen_bytes, prompt_bytes = frozen_path.read_bytes(), prompt_path.read_bytes()
                frozen = FrozenEnvironment.model_validate_json(frozen_bytes)
                prompt = read_recorded_prompt(prompt_path) if mode == "recorded" else read_native_prompt(prompt_path)
                assert frozen.prompt_mode == mode
                assert frozen.case_sha256 == case.fingerprint()
                assert frozen.inputs == prompt.frozen_inputs
                assert {str(path): file_sha256(path) for path in extra_inputs}.items() <= frozen.inputs.items()

                if change == "removed":
                    extra_inputs.pop()
                elif change == "added":
                    additional = directory / "supplemental-receipt.json"
                    additional.write_text("{}")
                    extra_inputs.append(additional)
                elif change == "modified":
                    extra_inputs[0].write_text("Changed recipe.\n")

                assert freeze(list(reversed(extra_inputs))) == (0 if change == "unchanged" else 1)
                assert frozen_path.read_bytes() == frozen_bytes
                assert prompt_path.read_bytes() == prompt_bytes
                if change == "modified":
                    with self.assertRaisesRegex(ValueError, "changed"):
                        if mode == "recorded":
                            read_recorded_prompt(prompt_path)
                        else:
                            read_native_prompt(prompt_path)

    @parameterized.expand([(0,), (123000,)])
    def test_default_cutoff_keeps_text_bounds_and_event_timestamps_aligned(self, microsecond: int) -> None:
        source = datetime(2030, 1, 1, microsecond=microsecond, tzinfo=UTC)
        now = datetime(2030, 2, 2, 12, microsecond=456789, tzinfo=UTC)
        target = ScoutEnvironmentCommand.default_cutoff(source, now)
        boundary = "2030-01-01T00:00:00Z"
        transform = EnvironmentTransform(
            source_cutoff=source, target_cutoff=target, record_ids=[], time_strings=[boundary]
        )

        self.assertLessEqual(target, now)
        self.assertLess((now - target).total_seconds(), 1)
        self.assertEqual(
            datetime.fromisoformat(transform.text(boundary)), datetime.fromisoformat(boundary) + transform.delta
        )

    def test_django_validation_errors_do_not_print_private_values(self) -> None:
        parser = argparse.ArgumentParser()
        add_arguments(parser)
        with TemporaryDirectory() as folder:
            directory = Path(folder).resolve()
            args = parser.parse_args(
                [
                    "--state-dir",
                    str(directory),
                    "prepare",
                    "--case",
                    str(directory / "case.json"),
                    "--bundle",
                    str(directory / "bundle"),
                ]
            )
            stderr = StringIO()
            with (
                patch.object(
                    ScoutEnvironmentCommand,
                    "prepare",
                    side_effect=DjangoValidationError("'private-example-value' has an invalid format."),
                ),
                redirect_stderr(stderr),
            ):
                result = execute(args)

        self.assertEqual(result, 1)
        self.assertNotIn("private-example-value", stderr.getvalue())

    @parameterized.expand([("prompt",), ("binding",), ("transformation",)])
    def test_dispatch_rejects_changed_runtime_prompt_or_missing_binding(self, changed: str) -> None:
        with TemporaryDirectory() as folder:
            directory = Path(folder).resolve()
            prompt_path = directory / "runtime-prompt.json"
            manifest_path = directory / "frozen.json"
            prompt = RecordedScoutPrompt(
                team_id=7,
                config_id=uuid4(),
                skill_name="example-scout",
                skill_version=1,
                allowed_tools=[],
                recorded_prompt="Preserve the recorded instructions.",
                harness_prompt_version="example-version",
                frozen_inputs={},
                frozen_manifest=str(manifest_path),
            )
            write_private_json(prompt_path, prompt)
            frozen = FrozenEnvironment(
                created_at=datetime(2030, 6, 4, 12, tzinfo=UTC),
                inputs={},
                team_id=prompt.team_id,
                config_id=prompt.config_id,
                runtime_prompt_path=str(prompt_path),
                runtime_prompt_sha256=file_sha256(prompt_path),
            )
            write_private_json(manifest_path, frozen)
            assert read_recorded_prompt(prompt_path) == prompt

            if changed == "prompt":
                write_private_json(prompt_path, prompt.model_copy(update={"recorded_prompt": "Changed instructions."}))
            elif changed == "transformation":
                changed_prompt = json.loads(prompt_path.read_bytes())
                changed_prompt["prompt_transformations"] = [
                    {
                        "source": "Preserve the recorded instructions.",
                        "replacement": "Use revised instructions.",
                        "reason": "An instruction update requires a new frozen reconstruction.",
                        "expected_occurrences": 1,
                    }
                ]
                write_private_json(prompt_path, changed_prompt)
            else:
                previous = json.loads(manifest_path.read_bytes())
                previous.pop("runtime_prompt_path")
                previous.pop("runtime_prompt_sha256")
                write_private_json(manifest_path, previous)

            with self.assertRaises((ValueError, ValidationError)):
                read_recorded_prompt(prompt_path)

    @parameterized.expand([("launch_count",), ("reservation",), ("report_checks",), ("live_cap",)])
    def test_edited_request_or_gateway_caps_cannot_reuse_an_inconsistent_budget(self, changed: str) -> None:
        variant = TrialComparisonVariant(
            id=uuid4(),
            label="baseline",
            launch_ids=[uuid4(), uuid4()],
            model="example-model",
            reasoning_effort="high",
        )
        request = TrialComparisonRequest(
            comparison_id=uuid4(), baseline_variant_id=variant.id, variants=[variant], expected_skill_version=1
        )
        plan = EvaluationPlan(
            mode="comparison",
            comparison_id=request.comparison_id,
            freeze_sha256="0" * 64,
            config_id=uuid4(),
            team_id=7,
            user_id=7,
            request=request.model_dump(mode="json"),
            reserved_usd=Decimal("70"),
            scout_cap_usd=Decimal("10"),
            judge_cap_usd=Decimal("5"),
            report_checks_per_run=2,
        )
        scout_cap = Decimal("10")
        plan.validate_budget(request, scout_cap=scout_cap, judge_cap=Decimal("5"))

        if changed == "launch_count":
            variant.launch_ids.append(uuid4())
        elif changed == "reservation":
            plan = plan.model_copy(update={"reserved_usd": Decimal("69")})
        elif changed == "report_checks":
            plan = plan.model_copy(update={"report_checks_per_run": 1})
        else:
            scout_cap = Decimal("11")

        with self.assertRaisesRegex(ValueError, "budget reservation"):
            plan.validate_budget(request, scout_cap=scout_cap, judge_cap=Decimal("5"))
