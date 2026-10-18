from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from pydantic import JsonValue

from posthog.models.scoping import team_scope
from posthog.storage.object_storage import ObjectStorageError

from products.signals.backend.models import SignalScoutRun
from products.signals.backend.scout_harness.eval_environment.schema import (
    ScoutEnvironmentCase,
    ScoutEnvironmentSeed,
    ScoutEnvironmentSkill,
)
from products.signals.backend.scout_harness.eval_environment.trials import EvaluationPlan, ScoutEvaluationTrials
from products.signals.backend.scout_harness.trial_comparison_types import TrialComparisonResult
from products.signals.backend.scout_harness.trial_launch import TrialLaunch
from products.signals.backend.test.test_scout_harness_api import _make_run


class TestScoutEvaluationExport(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(team_scope(self.team.id, canonical=True))
        self.context_id = uuid4()
        self.runs = [
            _make_run(
                self.team,
                task_run_status="completed",
                summary=f"Candidate {index}",
                metadata={"scout_trial": {"version": 1, "context_id": str(self.context_id)}},
            )
            for index in range(2)
        ]
        for run in self.runs:
            run.task_run.task.created_by = self.user
            run.task_run.task.save(update_fields=["created_by"])
        self.launches = {
            UUID(str(cast(dict[str, JsonValue], (run.metadata or {})["scout_trial"])["launch_id"])): TrialLaunch(
                id=UUID(str(cast(dict[str, JsonValue], (run.metadata or {})["scout_trial"])["launch_id"])),
                team_id=self.team.id,
                config_id=run.scout_config_id,
                user_id=self.user.id,
                context_id=self.context_id,
                created_at=timezone.now(),
                skill_name=run.skill_name,
                skill_version=run.skill_version,
                skill_body="Inspect this project.",
                runtime_adapter="codex",
                model="example-model",
                reasoning_effort="medium",
                request_hash="example",
            )
            for run in self.runs
        }
        self.trials = object.__new__(ScoutEvaluationTrials)
        self.trials.seed = ScoutEnvironmentSeed(
            environment_id="example",
            team_id=self.team.id,
            user_id=self.user.id,
            config_id=self.runs[0].scout_config_id,
            skill_id=uuid4(),
            identity_map={},
            time_delta_seconds=0,
            steering="",
        )
        self.trials.case = ScoutEnvironmentCase(
            environment_id="example",
            source_cutoff=timezone.now(),
            checkpoint=timezone.now(),
            skill=ScoutEnvironmentSkill(
                id=self.trials.seed.skill_id,
                name=self.runs[0].skill_name,
                version=1,
                origin="custom",
                body="Inspect this project.",
            ),
        )
        self.enterContext(
            patch(
                "products.signals.backend.scout_harness.trial_launch.read_trial_launch",
                side_effect=lambda _team, identifier: self.launches[identifier],
            )
        )

    def plan(self, *, mode: Literal["trial", "comparison"] = "comparison") -> EvaluationPlan:
        launch_id = next(iter(self.launches))
        variant_id = uuid4()
        return EvaluationPlan(
            mode=mode,
            config_id=self.trials.seed.config_id,
            team_id=self.team.id,
            user_id=self.user.id,
            freeze_sha256="example",
            request={
                "comparison_id": str(uuid4()),
                "baseline_variant_id": str(variant_id),
                "variants": [
                    {
                        "id": str(variant_id),
                        "label": "Baseline",
                        "launch_ids": [str(launch_id)],
                        "model": "example-model",
                        "reasoning_effort": "medium",
                    }
                ],
            },
            reserved_usd=Decimal("1"),
            scout_cap_usd=Decimal("1"),
            judge_cap_usd=Decimal("1"),
            report_checks_per_run=1,
        )

    @parameterized.expand(["launch_config", "task_operator"])
    def test_mismatched_binding_exports_no_private_state_or_trace(self, mismatch: str) -> None:
        launch_id = next(iter(self.launches))
        if mismatch == "launch_config":
            self.launches[launch_id] = self.launches[launch_id].model_copy(update={"config_id": uuid4()})
        else:
            self.runs[0].task_run.task.created_by = None
            self.runs[0].task_run.task.save(update_fields=["created_by"])
        with patch("products.signals.backend.scout_harness.eval_environment.trials.write_private_json") as write:
            self.trials.export(self.plan(mode="trial"), Path("unused.json"))
        exported = write.call_args.args[1]
        assert exported.result is None
        assert exported.log == ""
        assert exported.run_id is None
        assert exported.errors

    @parameterized.expand([False, True])
    def test_comparison_uses_saved_launches_and_reports_missing_objects_without_losing_other_runs(
        self, storage_error: bool
    ) -> None:
        plan = self.plan()
        launch_ids = list(self.launches)
        saved_plan = SimpleNamespace(
            context_id=self.context_id,
            request=SimpleNamespace(variants=[SimpleNamespace(launch_ids=launch_ids)]),
        )
        result = TrialComparisonResult(
            comparison_id=plan.comparison_id,
            config_id=plan.config_id,
            context_id=self.context_id,
            created_at=timezone.now(),
            baseline_variant_id=uuid4(),
            rubric_revision=1,
            variants=[],
            status="completed",
            error=None,
            evaluation=None,
        )
        second = self.runs[1]
        saved_result: dict[str, JsonValue] = {
            "version": 1,
            "run_id": str(second.id),
            "task_run_id": str(second.task_run_id),
            "launch_id": str(launch_ids[1]),
            "context_id": str(self.context_id),
            "status": "completed",
            "task_status": "in_progress",
        }

        def read_result(run: SignalScoutRun) -> dict[str, JsonValue] | None:
            if run.id == second.id:
                return saved_result
            if storage_error:
                raise ObjectStorageError("Unavailable")
            return None

        with (
            patch.object(
                self.trials,
                "_service",
                return_value=SimpleNamespace(read=lambda _: saved_plan, result=lambda _: result),
            ),
            patch("products.signals.backend.scout_harness.trial_result.read_trial_result", side_effect=read_result),
            patch(
                "products.tasks.backend.facade.api.get_task_run_log_urls",
                side_effect=lambda run_id, *_: (
                    ["missing", "present"] if run_id == self.runs[0].task_run_id else ["present"]
                ),
            ),
            patch(
                "posthog.storage.object_storage.head_object_strict",
                side_effect=lambda url: None if url == "missing" else {"ContentLength": 20},
            ),
            patch(
                "posthog.storage.object_storage.read",
                side_effect=lambda url, **_: None if url == "missing" else '{"message":"example"}\n',
            ),
            patch("products.signals.backend.scout_harness.eval_environment.trials.write_private_json") as write,
        ):
            self.trials.export(plan, Path("unused.json"))
        exported = write.call_args.args[1]
        assert exported["status"] == "completed"
        assert exported["comparison_id"] == str(plan.comparison_id)
        assert set(exported["run_exports"]) == {str(identifier) for identifier in launch_ids}
        first_export = exported["run_exports"][str(launch_ids[0])]
        assert first_export["result"]["summary"] == self.runs[0].summary
        assert first_export["result"]["private_state"]
        assert any("saved result" in message for message in first_export["errors"])
        assert any("object 1 is missing" in message for message in first_export["errors"])
        assert first_export["log"] == '{"message":"example"}\n'
        second_export = exported["run_exports"][str(launch_ids[1])]
        assert second_export["errors"] == []
        assert second_export["status"] == "completed"
        assert second_export["result"]["task_status"] == "in_progress"
