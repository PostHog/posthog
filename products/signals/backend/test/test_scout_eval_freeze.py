import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from unittest import TestCase

from parameterized import parameterized
from pydantic import ValidationError

from products.posthog_ai.eval_harness.environment.storage import file_sha256
from products.posthog_ai.eval_harness.environment.transform import EnvironmentTransform
from products.signals.backend.scout_harness.eval_environment.cli import ScoutEnvironmentCommand
from products.signals.backend.scout_harness.eval_environment.prompt import RecordedScoutPrompt, read_recorded_prompt
from products.signals.backend.scout_harness.eval_environment.trials import (
    EvaluationPlan,
    FrozenEnvironment,
    write_private_json,
)
from products.signals.backend.scout_harness.trial_comparison_types import TrialComparisonRequest, TrialComparisonVariant


class TestScoutEvaluationFreeze(TestCase):
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

    @parameterized.expand([("prompt",), ("binding",), ("transformation",)])
    def test_dispatch_rejects_changed_runtime_prompt_or_missing_binding(self, changed: str) -> None:
        with TemporaryDirectory() as folder:
            directory = Path(folder)
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
                created_at=datetime.now(UTC),
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
