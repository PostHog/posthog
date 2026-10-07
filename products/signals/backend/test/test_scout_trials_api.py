from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from typing import Literal, cast
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, PropertyMock, patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team
from posthog.models.scoping import team_scope
from posthog.storage import object_storage

from products.signals.backend.agent_runtime import AgentRuntime
from products.signals.backend.facade.rubrics import default_criteria
from products.signals.backend.models import (
    SignalReport,
    SignalReportCheck,
    SignalScoutConfig,
    SignalScoutNote,
    SignalScratchpad,
)
from products.signals.backend.scout_harness.model_selection import ScoutModel
from products.signals.backend.scout_harness.run_gates import check_fleet_gates
from products.signals.backend.scout_harness.tools.scratchpad import ScratchpadEntry
from products.signals.backend.scout_harness.trial_comparison import dispatch_trial_comparison
from products.signals.backend.scout_harness.trial_evaluation import TrialEvaluationError
from products.signals.backend.scout_harness.trial_launch import (
    ScoutTrialLaunchError,
    ScoutTrialsDisabled,
    assert_trial_model_access,
    create_trial_launch,
    load_trial_context,
    load_trial_launch,
    resolve_trial_source_model,
    scout_trials_enabled,
)
from products.signals.backend.scout_harness.trial_result import TrialWorkflowStatus, export_trial_result
from products.signals.backend.scout_harness.trial_state import ScoutTrialStore, TrialReport, memory_snapshot
from products.signals.backend.test.test_scout_harness_api import _authenticate_as_scout, _make_run
from products.signals.backend.test.test_scout_trial_judge import _reference_context
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.facade.run_config import get_default_model_for_runtime_adapter


class TestScoutTrialAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.trial_run = _make_run(self.team, metadata={"scout_trial": {"version": 1, "context_id": str(uuid4())}})
        self.other = _make_run(self.team, metadata={"scout_trial": {"version": 1, "context_id": str(uuid4())}})
        self.production = _make_run(self.team, summary="A normal completed investigation")
        self.memory_url = f"/api/projects/{self.team.id}/signals/scout/scratchpad/"
        self.trial_runs_url = f"/api/projects/{self.team.id}/signals/scout/runs/"
        snapshot = memory_snapshot([ScratchpadEntry(key="finding:shared", content="Starting value")])
        self.context = SimpleNamespace(memory=snapshot, notes=[], recent_runs=[], skill_name=self.trial_run.skill_name)
        for module in ("trial_inspection", "trial_launch", "trial_access"):
            context_patch = patch(
                f"products.signals.backend.scout_harness.{module}.load_trial_context", return_value=self.context
            )
            context_patch.start()
            self.addCleanup(context_patch.stop)

    def _as_trial(self) -> None:
        _authenticate_as_scout(self, scopes="signals_scout_experiment", sandbox_task_id=self.trial_run.task_run.task_id)

    def test_operator_run_reads_mark_only_trial_content(self) -> None:
        for run, private in ((self.trial_run, True), (self.production, False)):
            run.task_run.task.created_by = self.user
            run.task_run.task.save(update_fields=["created_by"])
            response = self.client.get(f"{self.trial_runs_url}{run.id}/")
            assert response.status_code == 200, response.data
            assert (response.get("X-PostHog-Suppress-Analytics") == "true") == private

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

    def test_note_search_filters_saved_content_before_preview_and_limit(self) -> None:
        saved_id = str(uuid4())
        self.context.notes = [
            {"id": str(uuid4()), "skill_name": "", "content": "Review delivery delays."},
            {"id": saved_id, "skill_name": "", "content": "Saved detail about checkout issues."},
            {"id": str(uuid4()), "skill_name": "", "content": "Another checkout note."},
        ]
        SignalScoutNote.objects.create(team=self.team, content="Production-only checkout detail.")
        self._as_trial()
        url = f"/api/projects/{self.team.id}/signals/scout/notes/"

        response = self.client.get(url, {"text": "CHECKOUT", "content_max_chars": "6", "limit": "1"})

        assert response.status_code == 200, response.data
        assert [(row["id"], row["content"]) for row in response.json()] == [(saved_id, "Saved ")]
        response = self.client.get(url, {"text": "production-only"})
        assert response.status_code == 200, response.data
        assert response.json() == []

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

    @parameterized.expand(["emit-signal", "report-check-create", "report-check-cancel", "check-result"])
    def test_unsupported_write_invalidates_own_trial_without_touching_another_run(self, action: str) -> None:
        self._as_trial()
        response = self.client.post(f"{self.trial_runs_url}{self.production.id}/{action}/", {})
        assert response.status_code == 404, response.data
        response = self.client.post(f"{self.trial_runs_url}{self.trial_run.id}/{action}/", {})
        assert response.status_code == 400, response.data
        assert ScoutTrialStore(self.trial_run).invalid_reason() is not None
        self.production.refresh_from_db()
        assert self.production.emitted_count == 0
        assert not SignalReportCheck.objects.for_team(self.team.id).exists()

    @parameterized.expand(["emissions/batch", "emissions/reports/batch", "token-costs"])
    def test_read_only_posts_do_not_invalidate_private_runs(self, action: str) -> None:
        self._as_trial()
        response = self.client.post(
            f"{self.trial_runs_url}{action}/", {"run_ids": [str(self.production.id)]}, format="json"
        )
        assert response.status_code == (403 if action == "token-costs" else 200), response.data
        assert ScoutTrialStore(self.trial_run).invalid_reason() is None

    @parameterized.expand([("report_level", False), ("per_run", True)])
    def test_report_check_reads_distinguish_own_private_reports_without_exposing_other_trials(
        self, _name: str, via_run: bool
    ) -> None:
        LLMSkill.objects.create(
            team=self.team,
            name=self.trial_run.skill_name,
            body="Review report evidence.",
            version=self.trial_run.skill_version,
            allowed_tools=["emit_report", "edit_report"],
        )
        own = ScoutTrialStore(self.trial_run)
        own_id, sibling_id = str(uuid4()), str(uuid4())
        own.capture_report(TrialReport(id=own_id, document={"title": "Private report"}), idempotency_key="own")
        ScoutTrialStore(self.other).capture_report(
            TrialReport(id=sibling_id, document={"title": "Sibling report"}), idempotency_key="sibling"
        )
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        live = SignalReport.objects.create(team=child, title="Live report", status=SignalReport.Status.READY)
        check = SignalReportCheck.objects.for_team(child.id).create(
            team=child,
            report=live,
            title="Review the live finding",
            kind=SignalReportCheck.Kind.AGENT,
            config={"instructions": "Review the live finding."},
            next_run_at=timezone.now() + timedelta(days=1),
            expires_at=timezone.now() + timedelta(days=7),
        )
        own.capture_report(
            TrialReport(id=str(live.id), source_report_id=str(live.id), document={"title": "Private edit"}),
            idempotency_key="edited",
        )
        other_team = Team.objects.create(organization=self.organization, name="Other")
        outside = SignalReport.objects.create(team=other_team, title="Other report", status=SignalReport.Status.READY)
        self._as_trial()
        run_segment = f"{self.trial_run.id}/" if via_run else ""
        url = f"{self.trial_runs_url}{run_segment}report-checks/"

        response = self.client.get(url, {"report_id": own_id})
        assert response.status_code == 400, response.data
        assert response.json()["detail"] == "Follow-up checks are unavailable for reports emitted in private trials."
        assert own.invalid_reason() is None
        assert own.get_report(own_id) is not None

        for report_id in (sibling_id, str(outside.id), str(uuid4())):
            response = self.client.get(url, {"report_id": report_id})
            assert response.status_code == 400, response.data
            assert response.json()["detail"] == f"report {report_id} not found"

        response = self.client.get(url, {"report_id": str(live.id)})
        assert response.status_code == 200, response.data
        assert [row["check_id"] for row in response.json()] == [str(check.id)]
        assert own.invalid_reason() is None

        _authenticate_as_scout(self, scopes="signals_scout_reports", sandbox_task_id=self.production.task_run.task_id)
        ordinary_segment = f"{self.production.id}/" if via_run else ""
        ordinary_url = f"{self.trial_runs_url}{ordinary_segment}report-checks/"
        response = self.client.get(ordinary_url, {"report_id": str(live.id)})
        assert response.status_code == 200, response.data
        assert [row["check_id"] for row in response.json()] == [str(check.id)]
        response = self.client.get(ordinary_url, {"report_id": own_id})
        assert response.status_code == 400, response.data
        assert response.json()["detail"] == f"report {own_id} not found"

    def test_trial_scope_without_bound_run_fails_closed(self) -> None:
        _authenticate_as_scout(
            self, scopes="signals_scout_experiment", sandbox_task_id=self.production.task_run.task_id
        )
        response = self.client.post(self.memory_url, {"key": "untrusted", "content": "Must not persist"})
        assert response.status_code == 403, response.data
        assert not SignalScratchpad.objects.filter(team=self.team, key="untrusted").exists()


@override_settings(
    SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=True,
    AI_GATEWAY_URL="https://gateway.example/v1",
    AI_GATEWAY_API_KEY="phs_synthetic_api_key",
    SANDBOX_AI_GATEWAY_URL=None,
    SANDBOX_AI_GATEWAY_MINT_KEY=None,
)
class TestScoutTrialLaunch(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        if self.team.id != 2:
            self.team = Team.objects.create(id=2, organization=self.organization, name="Internal example")
        self.enterContext(team_scope(self.team.id, canonical=True))
        self.trials_flag = self.enterContext(
            patch("products.signals.backend.scout_harness.trial_launch.feature_enabled", return_value=True)
        )
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
        extras = kwargs.get("extras")
        if key in self.documents and isinstance(extras, dict) and extras.get("IfNoneMatch") == "*":
            raise object_storage.ObjectStorageError("Object already exists")
        self.documents[key] = content

    def _internal_scout_base(self, *, real_fleet_gates: bool = False) -> str:
        if self.team.id != 2:
            self.team = Team.objects.create(id=2, organization=self.organization, name="Internal example")
            self.skill.team = self.team
            self.skill.save(update_fields=["team"])
            self.config.team = self.team
            self.config.save(update_fields=["team"])
        self.enterContext(team_scope(self.team.id, canonical=True))
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        for module in ("trial_inspection", "trial_views", "trial_comparison"):
            for function in (
                ("check_fleet_gates", "check_spend_gates") if module != "trial_views" else ("withheld_skills_for_team",)
            ):
                if function == "check_fleet_gates" and real_fleet_gates:
                    continue
                gate_patch = patch(
                    f"products.signals.backend.scout_harness.{module}.{function}",
                    return_value=set() if function == "withheld_skills_for_team" else None,
                )
                gate_patch.start()
                self.addCleanup(gate_patch.stop)
        return f"/api/projects/{self.team.id}/signals/scout/configs/{self.config.id}/"

    @parameterized.expand([False, None, RuntimeError("Synthetic flag failure")])
    def test_disabled_flag_blocks_api_and_queued_launch_but_keeps_setup_readable(self, flag: object) -> None:
        base = self._internal_scout_base()
        launch = create_trial_launch(config=self.config, user=self.user, launch_id=uuid4())
        saved = dict(self.documents)
        if isinstance(flag, Exception):
            self.trials_flag.side_effect = flag
        else:
            self.trials_flag.return_value = flag
        response = self.client.post(f"{base}trial/", {"launch_id": str(uuid4())}, format="json")
        assert response.status_code == 403, response.data
        assert "disabled" in str(response.data)
        with self.assertRaises(ScoutTrialsDisabled):
            create_trial_launch(config=self.config, user=self.user, launch_id=uuid4())
        with self.assertRaises(ScoutTrialsDisabled):
            load_trial_launch(self.team.id, launch.id)
        setup = self.client.get(f"{base}trial_setup/")
        assert setup.status_code == 200, setup.data
        assert not setup.json()["ready"]
        assert "disabled" in setup.json()["blocked_reason"]
        assert self.documents == saved

    @parameterized.expand([("trial_setup",), ("trial_history",), ("trial_comparison_history",)])
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

    @parameterized.expand(
        [
            ("SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE", False, "Private capture"),
            ("AI_GATEWAY_URL", "", "AI_GATEWAY_URL"),
            ("AI_GATEWAY_API_KEY", "", "AI_GATEWAY_API_KEY"),
        ]
    )
    def test_setup_remains_readable_when_unavailable_and_excludes_inaccessible_models(
        self, setting: str, value: object, blocked_reason: str
    ) -> None:
        self.enterContext(override_settings(**{setting: value}))
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
        assert blocked_reason in setup["blocked_reason"]
        assert "writes or external tools" in setup["blocked_reason"]
        assert setup["skill_body"] == self.skill.body
        assert setup["model"] == "gpt-5.5"
        assert setup["reasoning_effort"] == "medium"
        assert [choice["model"] for choice in setup["models"]] == ["gpt-5.5"]
        assert "medium" in setup["models"][0]["reasoning_efforts"]
        assert not self.documents
        with patch(
            "products.signals.backend.scout_harness.trial_inspection.get_supported_reasoning_efforts", return_value=[]
        ):
            assert self.client.get(f"{base}trial_setup/").json()["models"] == []

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
        self.trials_flag.return_value = False
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

    @parameterized.expand([1, 2048])
    def test_candidate_first_preserves_baseline_and_retry_identity(self, memory_entry_count: int) -> None:
        self.user.first_name = "Synthetic"
        self.user.last_name = "Operator"
        self.user.save(update_fields=["first_name", "last_name"])
        source_run = _make_run(self.team)
        content = "Synthetic shared observation. " + "a" * 40_960
        SignalScratchpad.objects.bulk_create(
            [
                SignalScratchpad(
                    team=self.team,
                    key=f"finding:synthetic-{index}",
                    content=content,
                    created_by_run=source_run,
                )
                for index in range(memory_entry_count)
            ]
        )
        expired_note = SignalScoutNote.objects.create(
            team=self.team,
            skill_name=source_run.skill_name,
            content="Synthetic historical guidance.",
            created_by=self.user,
            expires_at=timezone.now() - timedelta(days=1),
        )
        launch_id = uuid4()
        candidate = create_trial_launch(
            config=self.config,
            user=self.user,
            launch_id=launch_id,
            skill_body="Trace dependencies before reporting.",
            reasoning_effort="high",
        )
        saved_context = load_trial_context(self.team.id, candidate.context_id)
        assert len(saved_context.memory) == memory_entry_count
        assert all(entry["content"] == content for entry in saved_context.memory)
        assert all(entry["created_by_skill"] == source_run.skill_name for entry in saved_context.memory)
        assert all(str(source_run.task_run_id) in str(entry["created_by_run_url"]) for entry in saved_context.memory)
        assert saved_context.notes[0]["id"] == str(expired_note.id)
        assert saved_context.notes[0]["created_by_name"] == "Synthetic Operator"
        if memory_entry_count > 1:
            assert len(saved_context.model_dump_json().encode()) > 80 * 1024 * 1024
        SignalScratchpad.objects.for_team(self.team.id).filter(key="finding:synthetic-0").update(content="Live change.")
        expired_note.delete()
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
        assert baseline.context_id == candidate.context_id
        assert load_trial_context(self.team.id, baseline.context_id) == saved_context
        trial_run = _make_run(
            self.team, metadata={"scout_trial": {"version": 1, "context_id": str(candidate.context_id)}}
        )
        assert ScoutTrialStore(trial_run).search_memory(key="finding:synthetic-0")[0].content == content
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
        base = self._internal_scout_base()
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

    @parameterized.expand([False, True])
    def test_direct_trial_endpoints_require_staff_in_internal_project(self, other_project: bool) -> None:
        base = self._internal_scout_base()
        if other_project:
            other_team = Team.objects.create(organization=self.organization, name="Another example")
            base = base.replace("/projects/2/", f"/projects/{other_team.id}/")
        else:
            self.user.is_staff = False
            self.user.save(update_fields=["is_staff"])
        payload = {"launch_id": str(uuid4())}
        with patch(
            "products.signals.backend.temporal.agentic.scout_scheduler.start_trial_signals_scout_run"
        ) as dispatch:
            assert self.client.post(f"{base}trial/", payload, format="json").status_code == 404
            assert self.client.get(f"{base}trial_result/", payload).status_code == 404
            dispatch.assert_not_called()

    def test_revoked_model_refuses_new_execution_but_keeps_saved_launch_readable(self) -> None:
        launch = create_trial_launch(config=self.config, user=self.user, launch_id=uuid4())
        with patch(
            "products.signals.backend.scout_harness.trial_launch.get_model_access_error",
            return_value="Model access revoked",
        ):
            assert load_trial_launch(self.team.id, launch.id) == launch
            with self.assertRaisesMessage(ScoutTrialLaunchError, "Model access revoked"):
                assert_trial_model_access(launch)

    @parameterized.expand(
        [
            ("completed_task_cancelled_runner", "completed", "cancelled", False, "unknown"),
            ("failed_task_cancelled_runner", "failed", "cancelled", False, "unknown"),
            ("task_still_ending", "in_progress", "cancelled", False, "unknown"),
            ("recover_missing_export", "completed", None, False, "completed"),
            ("concurrent_runner_export", "completed", "cancelled", True, "completed"),
            ("task_finished_before_scout", "completed", None, False, "pending"),
            ("task_finished_controller_unavailable", "completed", None, False, "unknown"),
            ("controller_failed_task_active", "in_progress", None, False, "failed"),
            ("controller_cancelled_task_active", "in_progress", None, False, "cancelled"),
            ("runner_export_after_row_read", "completed", "completed", False, "pending"),
            ("scout_finished_task_not_started", "not_started", "completed", False, "unknown"),
            ("scout_finished_task_queued", "queued", "completed", False, "unknown"),
            ("scout_finished_task_active", "in_progress", "completed", False, "unknown"),
            ("scout_finished_task_failed", "failed", "completed", False, "unknown"),
            ("scout_finished_task_cancelled", "cancelled", "completed", False, "unknown"),
        ]
    )
    def test_poll_preserves_terminal_result(
        self,
        _label: str,
        task_status: str,
        saved_status: str | None,
        concurrent_export: bool,
        workflow_status: Literal["unknown", "completed", "pending", "failed", "cancelled"],
    ) -> None:
        self._internal_scout_base()
        launch = create_trial_launch(config=self.config, user=self.user, launch_id=uuid4())
        run = _make_run(
            self.team,
            scout_config=self.config,
            skill_name=self.skill.name,
            task_run_status=task_status,
            summary="The scout's final observation.",
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
        concurrent_read = _label == "runner_export_after_row_read"
        if saved_status is not None and not concurrent_export and not concurrent_read:
            export_trial_result(run, status=saved_status)

        def read(key: str, **kwargs: object) -> str | None:
            if concurrent_read and "/results/" in key and key not in self.documents:
                run.summary = "The finalized summary arrived after the database read."
                run.save(update_fields=["summary"])
                run.task_run.state["token_usage"] = {"input_tokens": 120, "output_tokens": 30}
                run.task_run.save(update_fields=["state"])
                export_trial_result(run, status="completed")
            return self.documents.get(key)

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
            patch("posthog.storage.object_storage.read", side_effect=read),
            patch(
                "products.signals.backend.scout_harness.trial_views.get_trial_workflow_status",
                return_value=TrialWorkflowStatus(status=workflow_status),
            ) as workflow,
            patch(
                "posthog.storage.object_storage.write",
                side_effect=concurrent_write if concurrent_export else self._write,
            ),
        ):
            first = self.client.get(url, {"launch_id": str(launch.id)})
            assert first.status_code == 200, first.data
            result = first.json()
            waiting = saved_status is None and workflow_status in {"pending", "unknown"}
            expected_status: str = "in_progress" if workflow_status == "pending" else workflow_status
            expected_status = saved_status or expected_status
            task_cleanup_pending = saved_status == "completed" and task_status not in {
                "completed",
                "failed",
                "cancelled",
            }
            if task_cleanup_pending:
                expected_status = "in_progress"
            elif saved_status == "completed" and task_status in {"failed", "cancelled"}:
                expected_status = task_status
            assert result["status"] == expected_status
            assert result["task_status"] == task_status
            assert result["export_error"] is None
            if concurrent_read:
                assert result["summary"] == run.summary
                assert result["input_tokens"] == 120
                assert result["output_tokens"] == 30
            if waiting:
                assert result["result_key"] is None
                assert not any("/results/" in key for key in self.documents)
                run.summary = "The scout finished after the task's completion signal."
                run.save(update_fields=["summary"])
                workflow.return_value = TrialWorkflowStatus(status="completed")
                finalized = self.client.get(url, {"launch_id": str(launch.id)})
                assert finalized.status_code == 200, finalized.data
                result = finalized.json()
                assert result["status"] == "completed"
                assert result["summary"] == run.summary
                assert json.loads(self.documents[result["result_key"]])["summary"] == run.summary
            if task_cleanup_pending:
                assert result["result_key"] is not None
                run.task_run.status = "completed"
                run.task_run.save(update_fields=["status"])
                finalized = self.client.get(url, {"launch_id": str(launch.id)})
                assert finalized.status_code == 200, finalized.data
                result = finalized.json()
                assert result["status"] == "completed"
                assert result["task_status"] == "completed"
                assert result["summary"] == run.summary
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
            "rubric_source": "saved",
        }
        with (
            patch(
                "products.signals.backend.scout_harness.run_gates._read_flag_payload",
                return_value={"guaranteed_team_ids": [self.team.id], "default_team_config": {"max_runs_per_day": 1}},
            ),
            patch("products.signals.backend.scout_harness.trial_views.check_spend_gates", return_value=None),
            patch("posthog.storage.object_storage.head_object_strict", return_value=None),
            patch(
                "products.signals.backend.scout_harness.trial_evaluation.get_trial_workflow_status",
                return_value=TrialWorkflowStatus(status="completed"),
            ),
            patch(
                "products.signals.backend.temporal.agentic.scout_trial_evaluation.start_trial_evaluation",
                return_value="synthetic-workflow",
            ) as dispatch,
            patch(
                "products.signals.backend.temporal.agentic.scout_trial_evaluation.get_trial_evaluation_status",
                return_value=TrialWorkflowStatus(status="pending"),
            ),
        ):
            rejection = check_fleet_gates(self.team.id)
            assert rejection is not None and rejection.reason == "daily_run_budget"
            unsaved = self.client.post(f"{base}trial_evaluation/", payload, format="json")
            assert unsaved.status_code == 400
            assert "Review and save" in str(unsaved.data)
            dispatch.assert_not_called()
            self.config.rubrics = {
                "revision": 1,
                "criteria": [criterion.model_dump(mode="json") for criterion in default_criteria()],
                "reference_context": _reference_context(
                    skill_id=str(self.skill.id), skill_name=self.skill.name, instructions=self.skill.body
                ).model_dump(mode="json"),
                "reference_generation_id": str(uuid4()),
            }
            self.config.save(update_fields=["rubrics"])
            response = self.client.post(f"{base}trial_evaluation/", payload, format="json")
            assert response.status_code == 202, response.data
            assert response.json()["request"] == payload
            with patch(
                "products.signals.backend.scout_harness.run_gates._read_flag_payload",
                return_value={"guaranteed_team_ids": [self.team.id], "skip_team_ids": [self.team.id]},
            ):
                blocked = self.client.post(f"{base}trial_evaluation/", payload, format="json")
                assert blocked.status_code == 403, blocked.data
            snapshot_key = next(
                key for key in self.documents if "/evaluations/" in key and key.endswith("/snapshot.json")
            )
            frozen = self.documents[snapshot_key]
            retry = self.client.post(f"{base}trial_evaluation/", payload, format="json")
            assert retry.status_code == 202, retry.data
            assert self.documents[snapshot_key] == frozen
            query = {"evaluation_id": evaluation_id}
            with override_settings(SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=False):
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
            "rubric_source": "saved",
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

    @parameterized.expand([(2, 0), (2, 2), (2, 4), (20, 0)])
    def test_comparison_freezes_the_plan_before_dispatch_and_restores_without_browser_state(
        self, variant_count: int, started_count: int
    ) -> None:
        base = self._internal_scout_base(real_fleet_gates=True)
        self.enterContext(
            patch(
                "products.signals.backend.scout_harness.team_limits.posthoganalytics.get_feature_flag_payload",
                return_value={
                    "guaranteed_team_ids": [self.team.id],
                    "default_team_config": {"max_runs_per_day": variant_count * 2},
                },
            )
        )
        variant_id = str(uuid4())
        comparison_id = str(uuid4())
        variants: list[dict[str, object]] = [
            {
                "id": variant_id,
                "label": "Baseline",
                "launch_ids": [str(uuid4()), str(uuid4())],
                "model": "gpt-5.5",
                "reasoning_effort": "medium",
            },
            {
                "id": str(uuid4()),
                "label": "Candidate",
                "launch_ids": [str(uuid4()), str(uuid4())],
                "model": "gpt-5.5",
                "reasoning_effort": "high",
                "skill_body": "Inspect the synthetic funnel.",
            },
        ]
        variants.extend(
            {
                "id": str(uuid4()),
                "label": f"Version {index + 1}",
                "launch_ids": [str(uuid4()), str(uuid4())],
                "model": "gpt-5.5",
                "reasoning_effort": "high",
            }
            for index in range(2, variant_count)
        )
        payload = {"comparison_id": comparison_id, "baseline_variant_id": variant_id, "variants": variants}
        reference = _reference_context(
            skill_id=str(self.skill.id), skill_name=self.skill.name, instructions=self.skill.body
        )
        self.config.rubrics = {
            "revision": 1,
            "criteria": [criterion.model_dump(mode="json") for criterion in default_criteria()],
            "reference_context": reference.model_dump(mode="json"),
            "reference_generation_id": str(uuid4()),
        }
        self.config.save(update_fields=["rubrics"])
        module = "products.signals.backend.temporal.agentic.scout_trial_comparison"
        storage_client = MagicMock()
        storage_client.list_objects_v2.side_effect = lambda **kwargs: {
            "Contents": [{"Key": key} for key in sorted(self.documents) if key.startswith(kwargs["Prefix"])][
                : kwargs["MaxKeys"]
            ]
        }
        with (
            patch(f"{module}.start_trial_comparison", side_effect=RuntimeError("Synthetic dispatch interruption")),
            patch.object(
                object_storage,
                "object_storage_client",
                return_value=object_storage.ObjectStorage(storage_client),
            ),
            patch(
                f"{module}.get_trial_comparison_status", return_value=TrialWorkflowStatus(status="not_started")
            ) as workflow_status,
        ):
            interrupted = self.client.post(f"{base}trial_comparison/", payload, format="json")
            assert interrupted.status_code == 500
            history = self.client.get(f"{base}trial_comparison_history/")
            assert history.status_code == 200, history.data
            assert [item["comparison_id"] for item in history.json()["results"]] == [comparison_id]
            assert history.json()["results"][0]["evaluation"] is None
            assert history.json()["results"][0]["status"] == "not_started"
            workflow_status.assert_not_called()
            saved = self.client.get(f"{base}trial_comparison_result/", {"comparison_id": comparison_id})
            assert saved.status_code == 200, saved.data
            assert saved.json()["rubric_revision"] == 1
            assert saved.json()["status"] == "not_started"
            assert "Inspect the synthetic funnel." not in str(saved.json())
        plan_key = f"signals/scout-trials/{self.team.id}/comparisons/{comparison_id}/plan.json"
        frozen = self.documents[plan_key]
        assert len([key for key in self.documents if "/launches/" in key]) == variant_count * 2
        assert (
            len({json.loads(value)["context_id"] for key, value in self.documents.items() if "/launches/" in key}) == 1
        )
        launch_ids = [launch_id for variant in variants for launch_id in cast(list[str], variant["launch_ids"])]
        for launch_id in launch_ids[:started_count]:
            _make_run(self.team, metadata={"scout_trial": {"version": 1, "launch_id": launch_id}})
        self.config.rubrics = {}
        self.config.save(update_fields=["rubrics"])
        with patch(f"{module}.start_trial_comparison", return_value="synthetic-workflow") as dispatch:
            resumed = self.client.post(
                f"{base}trial_comparison_resume/", {"comparison_id": comparison_id}, format="json"
            )
            assert resumed.status_code == 202, resumed.data
            retry = self.client.post(f"{base}trial_comparison/", payload, format="json")
            assert retry.status_code == 202, retry.data
            assert self.documents[plan_key] == frozen
            changed = {**payload, "note": "A different request"}
            assert self.client.post(f"{base}trial_comparison/", changed, format="json").status_code == 400
            assert dispatch.call_count == 2
            other_user = self._create_user("another-comparison-operator@example.com")
            other_user.is_staff = True
            other_user.save(update_fields=["is_staff"])
            self.client.force_login(other_user)
            assert (
                self.client.get(f"{base}trial_comparison_result/", {"comparison_id": comparison_id}).status_code == 404
            )
            assert (
                self.client.post(
                    f"{base}trial_comparison_resume/", {"comparison_id": comparison_id}, format="json"
                ).status_code
                == 404
            )
            assert self.client.post(f"{base}trial_comparison/", payload, format="json").status_code == 400
            assert dispatch.call_count == 2

    @parameterized.expand([("over_budget", 2, 400), ("exact_fit", 3, 202)])
    def test_comparison_checks_the_whole_batch_against_remaining_budget(
        self, _name: str, daily_budget: int, expected_status: int
    ) -> None:
        base = self._internal_scout_base(real_fleet_gates=True)
        _make_run(self.team)
        self.config.rubrics = {
            "revision": 1,
            "criteria": [criterion.model_dump(mode="json") for criterion in default_criteria()],
            "reference_context": _reference_context(
                skill_id=str(self.skill.id), skill_name=self.skill.name, instructions=self.skill.body
            ).model_dump(mode="json"),
            "reference_generation_id": str(uuid4()),
        }
        self.config.save(update_fields=["rubrics"])
        variant_id = str(uuid4())
        payload = {
            "comparison_id": str(uuid4()),
            "baseline_variant_id": variant_id,
            "variants": [
                {
                    "id": variant_id,
                    "label": "Baseline",
                    "launch_ids": [str(uuid4()), str(uuid4())],
                    "model": "gpt-5.5",
                    "reasoning_effort": "medium",
                }
            ],
        }
        with (
            patch(
                "products.signals.backend.scout_harness.team_limits.posthoganalytics.get_feature_flag_payload",
                return_value={
                    "guaranteed_team_ids": [self.team.id],
                    "default_team_config": {"max_runs_per_day": daily_budget},
                },
            ),
            patch(
                "products.signals.backend.temporal.agentic.scout_trial_comparison.start_trial_comparison",
                return_value="synthetic-workflow",
            ) as dispatch,
        ):
            response = self.client.post(f"{base}trial_comparison/", payload, format="json")
            assert response.status_code == expected_status, response.data
            if expected_status == 400:
                assert "daily scout run budget" in str(response.data)
                dispatch.assert_not_called()
                assert not self.documents
            else:
                dispatch.assert_called_once()
                _make_run(self.team)
                resumed = self.client.post(
                    f"{base}trial_comparison_resume/", {"comparison_id": payload["comparison_id"]}, format="json"
                )
                assert resumed.status_code == 400, resumed.data
                dispatch.assert_called_once()
                with (
                    patch("products.signals.backend.scout_harness.trial_comparison.sync_connect") as connect,
                    patch(
                        "products.signals.backend.temporal.agentic.scout_scheduler.start_trial_signals_scout_run"
                    ) as start_run,
                    self.assertRaisesMessage(TrialEvaluationError, "needs 2 scout runs"),
                ):
                    dispatch_trial_comparison(self.team.id, UUID(str(payload["comparison_id"])))
                connect.assert_not_called()
                start_run.assert_not_called()

    @parameterized.expand(["rubric", "model", "effort", "writes", "nonstaff", "invalid_id", "stale_version"])
    def test_comparison_rejects_unusable_setup_before_any_run_dispatch(self, invalid: str) -> None:
        base = self._internal_scout_base()
        variant_id = str(uuid4())
        variant = {
            "id": variant_id,
            "label": "Baseline",
            "launch_ids": [str(uuid4())],
            "model": "gpt-5.5",
            "reasoning_effort": "medium",
        }
        payload: dict[str, object] = {
            "comparison_id": str(uuid4()),
            "baseline_variant_id": variant_id,
            "variants": [variant],
        }
        if invalid != "rubric":
            self.config.rubrics = {
                "revision": 1,
                "criteria": [criterion.model_dump(mode="json") for criterion in default_criteria()],
                "reference_context": _reference_context(
                    skill_id=str(self.skill.id), skill_name=self.skill.name, instructions=self.skill.body
                ).model_dump(mode="json"),
                "reference_generation_id": str(uuid4()),
            }
            self.config.save(update_fields=["rubrics"])
        if invalid == "model":
            variant["model"] = "unsupported-synthetic-model"
        elif invalid == "effort":
            variant["reasoning_effort"] = "unsupported-effort"
        elif invalid == "writes":
            self.config.write_scopes = ["dashboard:write"]
            self.config.save(update_fields=["write_scopes"])
        elif invalid == "nonstaff":
            self.user.is_staff = False
            self.user.save(update_fields=["is_staff"])
        elif invalid == "invalid_id":
            payload["comparison_id"] = "not-a-uuid"
        elif invalid == "stale_version":
            payload["expected_skill_version"] = self.skill.version + 1
        with patch(
            "products.signals.backend.temporal.agentic.scout_trial_comparison.start_trial_comparison"
        ) as dispatch:
            result = self.client.post(f"{base}trial_comparison/", payload, format="json")
            assert result.status_code == (404 if invalid == "nonstaff" else 400), result.data
            dispatch.assert_not_called()
        assert not self.documents


class TestScoutTrialsGate(SimpleTestCase):
    @parameterized.expand([(2, True, True), (2, False, False), (2, None, False), (2, "true", False), (3, True, False)])
    def test_trials_flag_requires_exact_project_and_boolean_enablement(
        self, team_id: int, flag: object, expected: bool
    ) -> None:
        team = Team(id=team_id, uuid=uuid4(), parent_team_id=2 if team_id != 2 else None)
        with patch("products.signals.backend.scout_harness.trial_launch.feature_enabled", return_value=flag) as lookup:
            assert scout_trials_enabled(team) is expected
        if team_id != 2:
            lookup.assert_not_called()
        else:
            lookup.assert_called_once_with(
                "scout-trials",
                str(team.uuid),
                groups={"project": str(team.uuid)},
                group_properties={"project": {"id": team.id, "uuid": str(team.uuid)}},
                send_feature_flag_events=False,
            )


class TestTrialSourceModel(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "scout_pin_beats_pipeline_block",
                ScoutModel(model="gpt-5.5", runtime_adapter="codex", reasoning_effort="medium", service_tier="flex"),
                AgentRuntime(runtime_adapter="claude", model="claude-sonnet-4-6", reasoning_effort="high"),
                ScoutModel(model="gpt-5.5", runtime_adapter="codex", reasoning_effort="medium", service_tier="flex"),
            ),
            (
                "pipeline_block_with_runtime",
                ScoutModel(model=None, runtime_adapter=None),
                AgentRuntime(runtime_adapter="codex", model="gpt-5.5", reasoning_effort="xhigh", service_tier="flex"),
                ScoutModel(model="gpt-5.5", runtime_adapter="codex", reasoning_effort="xhigh", service_tier="flex"),
            ),
            (
                "model_only_pipeline_block_is_ignored",
                ScoutModel(model=None, runtime_adapter=None),
                AgentRuntime(model="claude-sonnet-4-6", reasoning_effort="high", service_tier="flex"),
                ScoutModel(model=get_default_model_for_runtime_adapter("claude"), runtime_adapter="claude"),
            ),
        ]
    )
    def test_source_model_matches_runner_resolution(
        self, _name: str, scout_choice: ScoutModel, pipeline_choice: AgentRuntime, expected: ScoutModel
    ) -> None:
        config = cast(
            SignalScoutConfig,
            SimpleNamespace(team=SimpleNamespace(), team_id=1, skill_name="signals-scout-example", model=None),
        )
        with (
            patch("products.signals.backend.scout_harness.trial_launch.resolve_scout_model", return_value=scout_choice),
            patch(
                "products.signals.backend.scout_harness.trial_launch.resolve_agent_runtime",
                return_value=pipeline_choice,
            ),
        ):
            assert resolve_trial_source_model(config, uuid4()) == expected
