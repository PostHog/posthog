from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import PropertyMock, patch

from django.test import override_settings

from products.signals.backend.agent_runtime import AgentRuntime
from products.signals.backend.models import SignalScoutConfig, SignalScratchpad
from products.signals.backend.scout_harness.model_selection import ScoutModel
from products.signals.backend.scout_harness.tools.scratchpad import ScratchpadEntry
from products.signals.backend.scout_harness.trial_launch import (
    ScoutTrialLaunchError,
    create_trial_launch,
    load_trial_context,
    load_trial_launch,
)
from products.signals.backend.scout_harness.trial_result import TrialWorkflowStatus
from products.signals.backend.scout_harness.trial_state import ScoutTrialStore, memory_snapshot
from products.signals.backend.test.test_scout_harness_api import _authenticate_as_scout, _make_run
from products.skills.backend.models.skills import LLMSkill


class TestScoutTrialAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.trial_run = _make_run(self.team, metadata={"scout_trial": {"version": 1, "context_id": str(uuid4())}})
        self.other = _make_run(self.team, metadata={"scout_trial": {"version": 1, "context_id": str(uuid4())}})
        self.production = _make_run(self.team, summary="A normal completed investigation")
        self.memory_url = f"/api/projects/{self.team.id}/signals/scout/scratchpad/"
        self.trial_runs_url = f"/api/projects/{self.team.id}/signals/scout/runs/"
        snapshot = memory_snapshot([ScratchpadEntry(key="finding:shared", content="Starting value")])
        context = SimpleNamespace(memory=snapshot, notes=[], recent_runs=[], skill_name=self.trial_run.skill_name)
        for module in ("trial_launch", "trial_access"):
            context_patch = patch(
                f"products.signals.backend.scout_harness.{module}.load_trial_context", return_value=context
            )
            context_patch.start()
            self.addCleanup(context_patch.stop)

    def _as_trial(self) -> None:
        _authenticate_as_scout(self, scopes="signals_scout_experiment", sandbox_task_id=self.trial_run.task_run.task_id)

    def test_memory_routes_from_credential_and_cannot_write_production_or_sibling(self) -> None:
        original = SignalScratchpad.objects.create(team=self.team, key="finding:shared", content="Production value")
        self._as_trial()
        response = self.client.post(
            self.memory_url, {"key": original.key, "content": "Private value", "run_id": str(self.other.id)}
        )
        assert response.status_code == 200, response.data
        response = self.client.get(self.memory_url, {"key": original.key})
        assert response.status_code == 200, response.data
        assert response.json()[0]["content"] == "Private value"
        assert ScoutTrialStore(self.other).search_memory(key=original.key)[0].content == "Starting value"
        original.refresh_from_db()
        assert original.content == "Production value"
        response = self.client.post(f"{self.memory_url}forget/", {"key": original.key})
        assert response.status_code == 200, response.data
        assert self.client.get(self.memory_url).json() == []
        assert SignalScratchpad.objects.filter(pk=original.pk).exists()

    def test_ordinary_scout_cannot_read_trial_runs_and_own_detail_hides_labels(self) -> None:
        config = SignalScoutConfig.objects.for_team(self.team.id).get(skill_name=self.trial_run.skill_name)
        config.emit = False
        config.save(update_fields=["emit"])
        _authenticate_as_scout(self, sandbox_task_id=self.production.task_run.task_id)
        response = self.client.get(self.trial_runs_url)
        assert response.status_code == 200, response.data
        assert [row["run_id"] for row in response.json()] == [str(self.production.id)]
        assert self.client.get(f"{self.trial_runs_url}{self.trial_run.id}/").status_code == 404
        self._as_trial()
        response = self.client.get(f"{self.trial_runs_url}{self.trial_run.id}/")
        assert response.status_code == 200, response.data
        assert "scout_trial" not in response.json()["metadata"]
        assert self.client.get(f"{self.trial_runs_url}{self.other.id}/").status_code == 404
        configs = self.client.get(f"/api/projects/{self.team.id}/signals/scout/configs/")
        assert configs.status_code == 200, configs.data
        own_config = next(row for row in configs.json() if row["skill_name"] == config.skill_name)
        assert own_config["emit"] is True
        config.refresh_from_db()
        assert config.emit is False

    def test_unsupported_write_invalidates_own_trial_without_touching_another_run(self) -> None:
        self._as_trial()
        response = self.client.post(f"{self.trial_runs_url}{self.production.id}/emit-signal/", {})
        assert response.status_code == 404, response.data
        response = self.client.post(f"{self.trial_runs_url}{self.trial_run.id}/emit-signal/", {})
        assert response.status_code == 400, response.data
        assert ScoutTrialStore(self.trial_run).invalid_reason() is not None
        self.production.refresh_from_db()
        assert self.production.emitted_count == 0

    def test_trial_scope_without_bound_run_fails_closed(self) -> None:
        _authenticate_as_scout(
            self, scopes="signals_scout_experiment", sandbox_task_id=self.production.task_run.task_id
        )
        response = self.client.post(self.memory_url, {"key": "untrusted", "content": "Must not persist"})
        assert response.status_code == 403, response.data
        assert not SignalScratchpad.objects.filter(team=self.team, key="untrusted").exists()


@override_settings(
    SCOUT_LIVE_TRIALS_ENABLED=True,
    SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=True,
)
class TestScoutTrialLaunch(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.skill = LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-example",
            body="Investigate a regression.",
            version=1,
            allowed_tools=["emit_report"],
        )
        self.config = SignalScoutConfig.objects.create(
            team=self.team, skill_name=self.skill.name, enabled=False, emit=False
        )
        self.documents: dict[str, str] = {}
        patches = [
            patch(
                "products.signals.backend.scout_harness.trial_launch.object_storage.read",
                side_effect=lambda key, **kwargs: self.documents.get(key),
            ),
            patch("products.signals.backend.scout_harness.trial_launch.object_storage.write", side_effect=self._write),
            patch(
                "products.signals.backend.scout_harness.trial_launch.resolve_scout_model",
                return_value=ScoutModel(model="gpt-5.5", runtime_adapter="codex", reasoning_effort="medium"),
            ),
            patch(
                "products.signals.backend.scout_harness.trial_launch.resolve_agent_runtime", return_value=AgentRuntime()
            ),
            patch("products.signals.backend.scout_harness.trial_launch.get_model_access_error", return_value=None),
        ]
        for mock_patch in patches:
            mock_patch.start()
            self.addCleanup(mock_patch.stop)

    def _write(self, key: str, content: str, **kwargs: object) -> None:
        assert key not in self.documents
        self.documents[key] = content

    def test_candidate_first_preserves_baseline_and_retry_identity(self) -> None:
        launch_id = uuid4()
        candidate = create_trial_launch(
            config=self.config,
            user=self.user,
            launch_id=launch_id,
            skill_body="Trace dependencies before reporting.",
            reasoning_effort="high",
        )
        baseline = create_trial_launch(
            config=self.config, user=self.user, launch_id=uuid4(), context_id=candidate.context_id
        )
        assert baseline.skill_body == self.skill.body
        assert baseline.reasoning_effort == "medium"
        assert candidate.reasoning_effort == "high"
        assert load_trial_context(self.team.id, candidate.context_id).skill_body == self.skill.body
        retry = create_trial_launch(
            config=self.config,
            user=self.user,
            launch_id=launch_id,
            skill_body="Trace dependencies before reporting.",
            reasoning_effort="high",
        )
        assert retry == candidate
        with self.assertRaisesMessage(ScoutTrialLaunchError, "different settings"):
            create_trial_launch(config=self.config, user=self.user, launch_id=launch_id, skill_body="Another prompt")
        self.skill.refresh_from_db()
        self.config.refresh_from_db()
        assert self.skill.body == baseline.skill_body
        assert not self.config.enabled and not self.config.emit

    def test_launch_rejects_unsupported_capabilities_and_model_effort_before_dispatch(self) -> None:
        rejected_id = uuid4()
        with self.assertRaisesMessage(ScoutTrialLaunchError, "not supported"):
            create_trial_launch(config=self.config, user=self.user, launch_id=rejected_id, reasoning_effort="invented")
        with self.assertRaisesMessage(ScoutTrialLaunchError, "different comparison note"):
            create_trial_launch(config=self.config, user=self.user, launch_id=rejected_id, note="A changed note")
        self.config.write_scopes = ["dashboard:write"]
        self.config.save()
        with self.assertRaisesMessage(ScoutTrialLaunchError, "do not support"):
            create_trial_launch(config=self.config, user=self.user, launch_id=uuid4())

    def test_worker_rechecks_project_access_after_launch(self) -> None:
        launch = create_trial_launch(config=self.config, user=self.user, launch_id=uuid4())
        with (
            patch(
                "products.signals.backend.scout_harness.trial_launch.UserAccessControl.has_project_access",
                new_callable=PropertyMock,
                return_value=False,
            ),
            self.assertRaisesMessage(ScoutTrialLaunchError, "no longer has access"),
        ):
            load_trial_launch(self.team.id, launch.id)

    def test_operator_launch_and_poll_use_saved_identity(self) -> None:
        base = f"/api/projects/{self.team.id}/signals/scout/configs/{self.config.id}/"
        launch_id = str(uuid4())
        with (
            patch("products.signals.backend.scout_harness.trial_views.check_fleet_gates", return_value=None),
            patch("products.signals.backend.scout_harness.trial_views.check_spend_gates", return_value=None),
            patch("products.signals.backend.scout_harness.trial_views.withheld_skills_for_team", return_value=set()),
            patch("products.signals.backend.scout_harness.trial_views.sync_connect"),
            patch(
                "products.signals.backend.scout_harness.trial_views.get_trial_workflow_status",
                return_value=TrialWorkflowStatus(status="pending"),
            ),
            patch(
                "products.signals.backend.temporal.agentic.scout_scheduler.start_trial_signals_scout_run",
                return_value="saved-workflow",
            ) as dispatch,
        ):
            response = self.client.post(f"{base}trial/", {"launch_id": launch_id}, format="json")
            assert response.status_code == 202, response.data
            assert response.json()["launch_id"] == launch_id
            assert dispatch.call_args.kwargs["launch_id"] == launch_id
            result = self.client.get(f"{base}trial-result/", {"launch_id": launch_id})
            assert result.status_code == 200, result.data
            assert result.json()["status"] == "pending"
            assert result.json()["cost_usd"] is None
            assert self.client.get(f"{base}trial-result/", {"launch_id": str(uuid4())}).status_code == 404
