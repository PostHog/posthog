from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import PropertyMock, patch

from django.test import override_settings

from parameterized import parameterized

from posthog.models import Team
from posthog.models.scoping import team_scope
from posthog.storage import object_storage

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
from products.signals.backend.scout_harness.trial_result import TrialWorkflowStatus, export_trial_result
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
        for module in ("trial_inspection", "trial_launch", "trial_access"):
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

    def _internal_scout_base(self) -> str:
        if self.team.id != 2:
            self.team = Team.objects.create(id=2, organization=self.organization, name="Internal example")
            self.skill.team = self.team
            self.skill.save(update_fields=["team"])
            self.config.team = self.team
            self.config.save(update_fields=["team"])
        self.enterContext(team_scope(self.team.id, canonical=True))
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        for module in ("trial_inspection", "trial_views"):
            for function in (
                ("check_fleet_gates", "check_spend_gates")
                if module == "trial_inspection"
                else ("withheld_skills_for_team",)
            ):
                gate_patch = patch(
                    f"products.signals.backend.scout_harness.{module}.{function}",
                    return_value=set() if function == "withheld_skills_for_team" else None,
                )
                gate_patch.start()
                self.addCleanup(gate_patch.stop)
        return f"/api/projects/{self.team.id}/signals/scout/configs/{self.config.id}/"

    @parameterized.expand([("trial_setup",), ("trial_history",)])
    def test_internal_inspection_requires_staff_and_exact_project(self, action: str) -> None:
        base = self._internal_scout_base()
        self.user.is_staff = False
        self.user.save(update_fields=["is_staff"])
        assert self.client.get(f"{base}{action}/").status_code == 404
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        other_team = Team.objects.create(organization=self.organization, name="Another example")
        assert (
            self.client.get(base.replace("/projects/2/", f"/projects/{other_team.id}/") + f"{action}/").status_code
            == 404
        )
        with patch(
            "products.signals.backend.scout_harness.trial_inspection.UserAccessControl.check_access_level_for_object",
            return_value=False,
        ):
            assert self.client.get(f"{base}{action}/").status_code == 403

    @override_settings(SCOUT_LIVE_TRIALS_ENABLED=False)
    def test_setup_remains_readable_when_disabled_and_excludes_inaccessible_models(self) -> None:
        base = self._internal_scout_base()
        self.config.write_scopes = ["dashboard:write"]
        self.config.save(update_fields=["write_scopes"])
        with patch(
            "products.signals.backend.scout_harness.trial_inspection.get_model_access_error",
            side_effect=lambda model, **kwargs: None if model == "gpt-5.5" else "Unavailable",
        ):
            response = self.client.get(f"{base}trial_setup/")
        assert response.status_code == 200, response.data
        setup = response.json()
        assert setup["ready"] is False
        assert "not enabled" in setup["blocked_reason"]
        assert "writes or external tools" in setup["blocked_reason"]
        assert setup["skill_body"] == self.skill.body
        assert setup["model"] == "gpt-5.5"
        assert setup["reasoning_effort"] == "medium"
        assert [choice["model"] for choice in setup["models"]] == ["gpt-5.5"]
        assert "medium" in setup["models"][0]["reasoning_efforts"]
        assert not self.documents

    def test_setup_reads_saved_source_and_rejects_another_operators_context(self) -> None:
        base = self._internal_scout_base()
        launch = create_trial_launch(config=self.config, user=self.user, launch_id=uuid4())
        self.skill.is_latest = False
        self.skill.save(update_fields=["is_latest"])
        LLMSkill.objects.create(
            team=self.team,
            name=self.skill.name,
            version=2,
            body="Investigate the revised source.",
            allowed_tools=["emit_report"],
        )
        saved = self.client.get(f"{base}trial_setup/", {"context_id": str(launch.context_id)})
        assert saved.status_code == 200, saved.data
        assert saved.json()["skill_body"] == self.skill.body
        assert saved.json()["skill_version"] == 1
        current = self.client.get(f"{base}trial_setup/")
        assert current.status_code == 200, current.data
        assert current.json()["skill_body"] == "Investigate the revised source."
        other_user = self._create_user("other-operator@example.com")
        context = load_trial_context(self.team.id, launch.context_id).model_copy(update={"user_id": other_user.id})
        context_key = next(key for key in self.documents if "/contexts/" in key)
        self.documents[context_key] = context.model_dump_json()
        assert self.client.get(f"{base}trial_setup/", {"context_id": str(launch.context_id)}).status_code == 404

    def test_history_only_lists_own_valid_private_runs_and_keeps_requested_settings(self) -> None:
        base = self._internal_scout_base()
        launch = create_trial_launch(config=self.config, user=self.user, launch_id=uuid4(), variant="Baseline")
        marker = {
            "version": 1,
            "launch_id": str(launch.id),
            "context_id": str(launch.context_id),
            "variant": "Baseline",
        }
        valid = _make_run(
            self.team,
            scout_config=self.config,
            skill_name=self.skill.name,
            metadata={"scout_trial": marker},
        )
        valid.task_run.task.created_by = self.user
        valid.task_run.task.origin_key = f"scout-trial:{launch.id}"
        valid.task_run.task.save(update_fields=["created_by", "origin_key"])
        valid.task_run.state = {"scout_trial": marker, "model": "Changed during execution"}
        valid.task_run.save(update_fields=["state"])
        other_operator = _make_run(self.team, scout_config=self.config, metadata={"scout_trial": marker})
        other_operator.task_run.task.created_by = self._create_user("another-operator@example.com")
        other_operator.task_run.task.save(update_fields=["created_by"])
        invalid = _make_run(self.team, scout_config=self.config, metadata={"scout_trial": marker})
        invalid.task_run.task.created_by = self.user
        invalid.task_run.task.save(update_fields=["created_by"])
        _make_run(self.team, scout_config=self.config)
        response = self.client.get(f"{base}trial_history/")
        assert response.status_code == 200, response.data
        history = response.json()
        assert len(history["results"]) == 1
        assert history["results"][0]["launch_id"] == str(launch.id)
        assert history["results"][0]["context_id"] == str(launch.context_id)
        assert history["results"][0]["model"] == launch.model
        assert history["results"][0]["reasoning_effort"] == launch.reasoning_effort
        assert history["results"][0]["task_run_id"] == str(valid.task_run_id)
        assert history["has_more"] is False
        assert "skill_body" not in history["results"][0]

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
            result = self.client.get(f"{base}trial_result/", {"launch_id": launch_id})
            assert result.status_code == 200, result.data
            assert result.json()["status"] == "pending"
            assert result.json()["cost_usd"] is None
            assert self.client.get(f"{base}trial_result/", {"launch_id": str(uuid4())}).status_code == 404

    @parameterized.expand(
        [
            ("completed_task_cancelled_runner", "completed", "cancelled", False),
            ("failed_task_cancelled_runner", "failed", "cancelled", False),
            ("task_still_ending", "in_progress", "cancelled", False),
            ("recover_missing_export", "completed", None, False),
            ("concurrent_runner_export", "completed", "cancelled", True),
        ]
    )
    def test_poll_preserves_terminal_result(
        self, _label: str, task_status: str, saved_status: str | None, concurrent_export: bool
    ) -> None:
        launch = create_trial_launch(config=self.config, user=self.user, launch_id=uuid4())
        run = _make_run(
            self.team,
            scout_config=self.config,
            skill_name=self.skill.name,
            task_run_status=task_status,
            metadata={"scout_trial": {"version": 1, "launch_id": str(launch.id), "context_id": str(launch.context_id)}},
        )
        run.task_run.task.created_by = self.user
        run.task_run.task.save(update_fields=["created_by"])
        run.task_run.state = {
            "runtime_adapter": launch.runtime_adapter,
            "model": launch.model,
            "reasoning_effort": launch.reasoning_effort,
            "service_tier": launch.service_tier,
        }
        run.task_run.save(update_fields=["state"])
        if saved_status is not None and not concurrent_export:
            export_trial_result(run, status=saved_status)

        def concurrent_write(key: str, content: str, **kwargs: object) -> None:
            result = json.loads(content)
            result["status"] = saved_status
            self.documents[key] = json.dumps(result)
            extras = kwargs.get("extras")
            if isinstance(extras, dict) and extras.get("IfNoneMatch") == "*":
                raise object_storage.ObjectStorageError("A runner export already exists.")
            self.documents[key] = content

        url = f"/api/projects/{self.team.id}/signals/scout/configs/{self.config.id}/trial_result/"
        with (
            patch("products.signals.backend.scout_harness.trial_views.withheld_skills_for_team", return_value=set()),
            patch(
                "products.signals.backend.scout_harness.trial_views.get_trial_workflow_status",
                return_value=TrialWorkflowStatus(status="unknown"),
            ),
            patch(
                "posthog.storage.object_storage.write",
                side_effect=concurrent_write if concurrent_export else self._write,
            ),
        ):
            first = self.client.get(url, {"launch_id": str(launch.id)})
            assert first.status_code == 200, first.data
            result = first.json()
            assert result["status"] == (saved_status or task_status)
            assert result["task_status"] == task_status
            assert result["export_error"] is None
            saved_content = self.documents[result["result_key"]]
            second = self.client.get(url, {"launch_id": str(launch.id)})
        assert second.status_code == 200, second.data
        assert second.json() == result
        assert self.documents[result["result_key"]] == saved_content

    def test_evaluation_endpoints_save_exact_request_and_reject_another_operator(self) -> None:
        base = self._internal_scout_base()
        launch = create_trial_launch(config=self.config, user=self.user, launch_id=uuid4(), variant="Baseline")
        marker = {"version": 1, "launch_id": str(launch.id), "context_id": str(launch.context_id)}
        run = _make_run(
            self.team,
            scout_config=self.config,
            skill_name=self.skill.name,
            task_run_status="completed",
            metadata={"scout_trial": marker},
            summary="The synthetic checkout error has a clear reproduction.",
        )
        run.task_run.task.created_by = self.user
        run.task_run.task.origin_product = "signals_scout"
        run.task_run.task.origin_key = f"scout-trial:{launch.id}"
        run.task_run.task.save(update_fields=["created_by", "origin_product", "origin_key"])
        run.task_run.state = {
            "scout_trial": marker,
            "runtime_adapter": launch.runtime_adapter,
            "model": launch.model,
            "reasoning_effort": launch.reasoning_effort,
            "service_tier": launch.service_tier,
        }
        run.task_run.save(update_fields=["state"])
        variant_id = str(uuid4())
        variant = {"id": variant_id, "label": "Baseline", "launch_ids": [str(launch.id)]}
        evaluation_id = str(uuid4())
        payload = {
            "evaluation_id": evaluation_id,
            "baseline_variant_id": variant_id,
            "variants": [variant],
            "rubric_source": "mock",
        }
        with (
            patch("products.signals.backend.scout_harness.trial_views.check_fleet_gates", return_value=None),
            patch("products.signals.backend.scout_harness.trial_views.check_spend_gates", return_value=None),
            patch("posthog.storage.object_storage.head_object", return_value=None),
            patch(
                "products.signals.backend.temporal.agentic.scout_trial_evaluation.start_trial_evaluation",
                return_value="synthetic-workflow",
            ),
            patch(
                "products.signals.backend.temporal.agentic.scout_trial_evaluation.get_trial_evaluation_status",
                return_value=TrialWorkflowStatus(status="pending"),
            ),
        ):
            response = self.client.post(f"{base}trial_evaluation/", payload, format="json")
            assert response.status_code == 202, response.data
            assert response.json()["request"] == payload
            snapshot_key = next(
                key for key in self.documents if "/evaluations/" in key and key.endswith("/snapshot.json")
            )
            frozen = self.documents[snapshot_key]
            retry = self.client.post(f"{base}trial_evaluation/", payload, format="json")
            assert retry.status_code == 202, retry.data
            assert self.documents[snapshot_key] == frozen
            query = {"evaluation_id": evaluation_id}
            with override_settings(SCOUT_LIVE_TRIALS_ENABLED=False, SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=False):
                saved = self.client.get(f"{base}trial_evaluation_result/", query)
            assert saved.status_code == 200, saved.data
            assert saved.json()["request"] == payload
            assert saved.json()["report"] is None
            with patch(
                "products.signals.backend.temporal.agentic.scout_trial_evaluation.get_trial_evaluation_status",
                return_value=TrialWorkflowStatus(status="completed"),
            ):
                missing_report = self.client.get(f"{base}trial_evaluation_result/", query)
            assert missing_report.status_code == 200
            assert missing_report.json()["status"] == "unknown"
            assert missing_report.json()["report"] is None
            assert "report is unavailable" in missing_report.json()["error"]
            changed = {**payload, "variants": [{**variant, "label": "Changed label"}]}
            assert self.client.post(f"{base}trial_evaluation/", changed, format="json").status_code == 400
            other_user = self._create_user("other-evaluator@example.com")
            other_user.is_staff = True
            other_user.save(update_fields=["is_staff"])
            self.client.force_login(other_user)
            assert self.client.get(f"{base}trial_evaluation_result/", query).status_code == 404

    def test_evaluation_rejects_nonstaff_and_invalid_input_before_dispatch(self) -> None:
        base = self._internal_scout_base()
        evaluation_id = str(uuid4())
        payload = {
            "evaluation_id": evaluation_id,
            "baseline_variant_id": str(uuid4()),
            "variants": [{"id": str(uuid4()), "label": "Baseline", "launch_ids": [str(uuid4())]}],
            "rubric_source": "mock",
        }
        with patch(
            "products.signals.backend.temporal.agentic.scout_trial_evaluation.start_trial_evaluation"
        ) as dispatch:
            self.user.is_staff = False
            self.user.save(update_fields=["is_staff"])
            assert self.client.post(f"{base}trial_evaluation/", payload, format="json").status_code == 404
            assert (
                self.client.get(f"{base}trial_evaluation_result/", {"evaluation_id": evaluation_id}).status_code == 404
            )
            self.user.is_staff = True
            self.user.save(update_fields=["is_staff"])
            invalid = {**payload, "evaluation_id": "not-a-uuid"}
            assert self.client.post(f"{base}trial_evaluation/", invalid, format="json").status_code == 400
            dispatch.assert_not_called()
