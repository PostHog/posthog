from collections.abc import Iterator
from contextlib import contextmanager

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.constants import AvailableFeature
from posthog.models import EventDefinition, User
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.team.team import Team

from products.access_control.backend.facade.testing import create_access_control
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.signals.backend.facade.onboarding import InboxOnboarding
from products.signals.backend.models import SignalScoutConfig, SignalSourceConfig, SignalTeamConfig
from products.signals.backend.onboarding_activation import InboxOnboardingActivation
from products.signals.backend.scout_harness.lazy_seed import seed_canonical_skills
from products.signals.backend.tasks import launch_inbox_onboarding_job


class TestQuickInboxActivation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/signals/onboarding/"
        SignalTeamConfig.objects.get_or_create(team=self.team)
        self.source = SignalSourceConfig.objects.create(
            team=self.team, source_product="error_tracking", source_type="issue_created", enabled=True
        )
        self.draft = {
            "step": "github",
            "sources": [{"source_product": "error_tracking", "source_type": "issue_created", "enabled": True}],
            "scanner_ids": [],
            "suggestions": [],
            "automatic_implementation": False,
            "implementation_priority": "P1",
        }

    @contextmanager
    def _quick_activation_dependencies(
        self, *, ubp: bool | None = True, pilot: bool = False
    ) -> Iterator[dict[str, bool | None]]:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        Integration.objects.get_or_create(team=self.team, kind="github")
        flags = {"self-driving-ubp": ubp, "self-driving-github-optional": pilot}
        temporal = MagicMock(start_workflow=AsyncMock())
        with (
            patch("posthoganalytics.feature_enabled", side_effect=lambda key, *args, **kwargs: flags.get(key, False)),
            patch("posthoganalytics.get_feature_flag", return_value=False),
            patch(
                "posthoganalytics.get_feature_flag_payload",
                return_value={
                    "guaranteed_team_ids": [999999] if pilot else ["*"],
                    "default_team_config": {"max_enabled_scouts": 100},
                },
            ),
            patch("posthoganalytics.capture"),
            patch.object(
                GitHubIntegration, "list_repositories", return_value=([{"full_name": "example/product"}], False)
            ),
            patch("products.signals.backend.quota.is_team_limited", return_value=False),
            patch("products.signals.backend.source_backfill.sync_connect", return_value=temporal),
        ):
            yield flags

    @parameterized.expand(
        [
            (False, False, True, False),
            (True, False, False, False),
            (False, True, False, False),
            (False, False, True, True),
            (True, False, False, False, True),
        ]
    )
    def test_quick_activation_applies_reviewed_defaults_once(
        self, ubp: bool, pilot: bool, automatic: bool, child_environment: bool, existing_schedule: bool = False
    ) -> None:
        canonical_team = self.team
        if child_environment:
            config = SignalTeamConfig.objects.get(team=canonical_team)
            config.autostart_enabled = True
            config.save()
            self.team = Team.objects.create(organization=self.organization, parent_team=canonical_team, name="Child")
            SignalTeamConfig.objects.get_or_create(team=self.team)
            self.url = f"/api/projects/{self.team.id}/signals/onboarding/"
        self.team.ingested_event = True
        self.team.save()
        for name in ("$exception", "$ai_generation", "$pageview"):
            EventDefinition.objects.create(
                team=self.team, project_id=self.team.project_id, name=name, last_seen_at=timezone.now()
            )
        SignalSourceConfig.objects.create(team=self.team, source_product="github", source_type="issue", enabled=False)
        scanner = ReplayScanner.objects.create(
            team=self.team, name="Checkout", created_by=self.user, enabled=True, emits_signals=False
        )
        before_sources = list(SignalSourceConfig.objects.filter(team=self.team).values_list("id", "enabled"))
        with (
            self._quick_activation_dependencies(ubp=ubp, pilot=pilot),
            patch.object(launch_inbox_onboarding_job, "delay") as launch,
        ):
            if existing_schedule:
                seed_canonical_skills(canonical_team)
                SignalScoutConfig.objects.create(
                    team=canonical_team,
                    skill_name="signals-scout-general",
                    enabled=True,
                    emit=True,
                    run_interval_minutes=1800,
                    run_cron_schedule="0 10 * * *",
                )
            before_scouts = list(SignalScoutConfig.objects.for_team(canonical_team.id).values())
            preview = self.client.get(f"{self.url}activation/")
            assert preview.status_code == 200, preview.content
            assert preview.json()["can_activate"], preview.json()
            assert preview.json()["automatic_implementation"] is automatic
            assert list(SignalScoutConfig.objects.for_team(canonical_team.id).values()) == before_scouts
            if existing_schedule:
                assert preview.json()["general_scout"]["run_cron_schedule"] == "0 10 * * *"
            if child_environment:
                assert f"parent project {canonical_team.id}" in preview.json()["setup_description"]
                assert "automatic pull requests will be turned off" in preview.json()["setup_description"]
            assert (
                list(SignalSourceConfig.objects.filter(team=self.team).values_list("id", "enabled")) == before_sources
            )
            config = SignalTeamConfig.objects.get(team=self.team)
            assert config.onboarding is None and config.autostart_enabled is None
            expected = {
                "expected_activation_mode": preview.json()["activation_mode"],
                "expected_automatic_implementation": automatic,
            }
            with self.captureOnCommitCallbacks(execute=True):
                activated = self.client.post(f"{self.url}activate/", expected, format="json")
            assert activated.status_code == 200, activated.content
            assert activated.json()["state"] == "completed"
            config = SignalTeamConfig.objects.get(team=self.team)
            assert config.onboarding is not None
            assert config.autostart_enabled is automatic
            assert config.default_autostart_priority == "P1"
            assert config.onboarding["entrypoint"] == "mcp_error_tracking"
            assert config.onboarding["activated_by"] == self.user.id
            scanner.refresh_from_db()
            assert scanner.emits_signals
            assert config.onboarding["draft"]["scanner_ids"] == [str(scanner.id)]
            assert {(row["source_product"], row["source_type"]) for row in config.onboarding["draft"]["sources"]} == {
                ("error_tracking", "issue_created"),
                ("error_tracking", "issue_reopened"),
                ("error_tracking", "issue_spiking"),
                ("health_checks", "health_issue"),
                ("llm_analytics", "evaluation_report"),
                ("analytics", "anomaly_investigation"),
            }
            general = SignalScoutConfig.objects.for_team(canonical_team.id).get(skill_name="signals-scout-general")
            if child_environment:
                assert SignalTeamConfig.objects.get(team=canonical_team).autostart_enabled is False
            assert general.enabled and general.emit
            assert general.enabled_by_id == (None if existing_schedule else self.user.id)
            assert general.status == SignalScoutConfig.Status.ACTIVE
            assert general.status_changed_by_id == (None if existing_schedule else self.user.id)
            if existing_schedule:
                assert general.run_interval_minutes == 1800
                assert general.run_cron_schedule == "0 10 * * *"
            general.enabled = False
            general.run_interval_minutes = 1800
            general.run_cron_schedule = "0 10 * * *"
            general.save()
            config.autostart_enabled = False
            config.onboarding["jobs"] = {"scout": "started", "recommendations": "skipped"}
            config.save()
            dispatches = launch.call_count
            with self.captureOnCommitCallbacks(execute=True):
                repeated = self.client.post(f"{self.url}activate/", expected, format="json")
            assert repeated.status_code == 200, repeated.content
            assert repeated.json()["automatic_implementation"] is False
            assert repeated.json()["general_scout"] == {
                "skill_name": "signals-scout-general",
                "run_interval_minutes": 1800,
                "run_cron_schedule": "0 10 * * *",
            }
            general.refresh_from_db()
            assert not general.enabled
            assert launch.call_count == dispatches

    def test_quick_activation_retries_dispatch_after_settings_committed(self) -> None:
        expected = {"expected_activation_mode": "standard", "expected_automatic_implementation": False}
        with self._quick_activation_dependencies():
            with patch.object(launch_inbox_onboarding_job, "delay", side_effect=RuntimeError("Queue unavailable")):
                with (
                    self.assertRaisesRegex(RuntimeError, "Queue unavailable"),
                    self.captureOnCommitCallbacks(execute=True),
                ):
                    first = self.client.post(f"{self.url}activate/", expected, format="json")
                    assert first.status_code == 200, first.content
            config = SignalTeamConfig.objects.get(team=self.team)
            assert config.onboarding is not None
            assert config.onboarding["completed_at"]
            config.onboarding["jobs"] = {"scout": "failed", "recommendations": "started"}
            config.autostart_enabled = True
            config.save()
            general = SignalScoutConfig.objects.for_team(self.team.id).get(skill_name="signals-scout-general")
            general.enabled = False
            general.save()
            with (
                patch.object(launch_inbox_onboarding_job, "delay") as launch,
                self.captureOnCommitCallbacks(execute=True),
            ):
                retried = self.client.post(f"{self.url}activate/", expected, format="json")
            assert retried.status_code == 200, retried.content
            assert retried.json()["automatic_implementation"] is True
            assert {call.args for call in launch.call_args_list} == {(self.team.id, "scout")}
            general.refresh_from_db()
            assert not general.enabled

    def test_quick_activation_preserves_a_completion_that_wins_during_repository_checks(self) -> None:
        expected = {"expected_activation_mode": "standard", "expected_automatic_implementation": False}
        repository_checks = 0
        completed_scout_ids: list[str] = []
        completed_source_ids: list[str] = []

        def repository_response(*_args: object, **_kwargs: object) -> tuple[list[dict[str, str]], bool]:
            nonlocal repository_checks
            repository_checks += 1
            if repository_checks == 2:
                competing = self.client.post(f"{self.url}activate/", expected, format="json")
                assert competing.status_code == 200, competing.content
                config = SignalTeamConfig.objects.get(team=self.team)
                assert config.onboarding is not None
                config.onboarding["jobs"] = {"scout": "started", "recommendations": "skipped"}
                config.autostart_enabled = True
                config.save()
                general = SignalScoutConfig.objects.for_team(self.team.id).get(skill_name="signals-scout-general")
                general.enabled = False
                general.save()
                completed_scout_ids.extend(
                    str(pk) for pk in SignalScoutConfig.objects.for_team(self.team.id).values_list("pk", flat=True)
                )
                completed_source_ids.extend(
                    str(pk) for pk in SignalSourceConfig.objects.filter(team=self.team).values_list("pk", flat=True)
                )
            return [{"full_name": "example/product"}], False

        with (
            self._quick_activation_dependencies(),
            patch.object(GitHubIntegration, "list_repositories", side_effect=repository_response),
            patch.object(launch_inbox_onboarding_job, "delay") as launch,
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.post(f"{self.url}activate/", expected, format="json")
        assert response.status_code == 200, response.content
        assert response.json()["state"] == "completed"
        assert response.json()["automatic_implementation"] is True
        assert completed_scout_ids and completed_source_ids
        assert set(completed_scout_ids) == {
            str(pk) for pk in SignalScoutConfig.objects.for_team(self.team.id).values_list("pk", flat=True)
        }
        assert set(completed_source_ids) == {
            str(pk) for pk in SignalSourceConfig.objects.filter(team=self.team).values_list("pk", flat=True)
        }
        assert not SignalScoutConfig.objects.for_team(self.team.id).get(skill_name="signals-scout-general").enabled
        assert launch.call_count == 2

    def test_quick_activation_rolls_back_sources_scanners_and_scouts_when_completion_fails(self) -> None:
        self.source.delete()
        EventDefinition.objects.create(
            team=self.team, project_id=self.team.project_id, name="$exception", last_seen_at=timezone.now()
        )
        scanner = ReplayScanner.objects.create(
            team=self.team, name="Checkout", created_by=self.user, enabled=True, emits_signals=False
        )

        def fail_completion(*_args: object, **_kwargs: object) -> None:
            assert ReplayScanner.objects.get(team=self.team, pk=scanner.pk).emits_signals
            assert SignalSourceConfig.objects.filter(team=self.team, source_product="error_tracking").exists()
            assert SignalScoutConfig.objects.for_team(self.team.id).get(skill_name="signals-scout-general").enabled
            raise ValueError("Settings changed before completion")

        with (
            self._quick_activation_dependencies(),
            patch.object(InboxOnboarding, "complete_prepared", side_effect=fail_completion),
            patch.object(launch_inbox_onboarding_job, "delay") as launch,
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.post(
                f"{self.url}activate/",
                {"expected_activation_mode": "standard", "expected_automatic_implementation": False},
                format="json",
            )
        assert response.status_code == 400, response.content
        config = SignalTeamConfig.objects.get(team=self.team)
        assert config.onboarding is None and config.autostart_enabled is None
        assert not SignalSourceConfig.objects.filter(team=self.team).exists()
        assert not SignalScoutConfig.objects.for_team(self.team.id).exists()
        scanner.refresh_from_db()
        assert not scanner.emits_signals
        launch.assert_not_called()

    def test_quick_activation_retries_error_backfill_without_reapplying_settings_or_duplicate_work(self) -> None:
        self.source.delete()
        EventDefinition.objects.create(
            team=self.team, project_id=self.team.project_id, name="$exception", last_seen_at=timezone.now()
        )
        expected = {"expected_activation_mode": "standard", "expected_automatic_implementation": False}
        temporal = MagicMock(
            start_workflow=AsyncMock(
                side_effect=[
                    RuntimeError("Temporal unavailable"),
                    None,
                    WorkflowAlreadyStartedError("backfill", "backfill-error-tracking"),
                ]
            )
        )
        with (
            self._quick_activation_dependencies(),
            patch("products.signals.backend.source_backfill.sync_connect", return_value=temporal),
            patch("products.signals.backend.onboarding_activation.ph_scoped_capture"),
            patch.object(launch_inbox_onboarding_job, "delay") as launch,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                activated = self.client.post(f"{self.url}activate/", expected, format="json")
            assert activated.status_code == 200, activated.content
            assert activated.json()["jobs"]["error_tracking_backfill"] == "pending"
            assert launch.call_count == 3
            config = SignalTeamConfig.objects.get(team=self.team)
            assert config.onboarding is not None
            config.onboarding["jobs"].update(scout="started", recommendations="skipped")
            config.autostart_enabled = True
            config.save()
            general = SignalScoutConfig.objects.for_team(self.team.id).get(skill_name="signals-scout-general")
            general.enabled = False
            general.save()
            source_ids = set(SignalSourceConfig.objects.filter(team=self.team).values_list("pk", flat=True))
            activation = InboxOnboardingActivation(self.team.id)
            with self.assertRaisesRegex(RuntimeError, "Temporal unavailable"):
                activation.run("error_tracking_backfill")
            config.refresh_from_db()
            assert config.onboarding is not None
            assert config.onboarding["jobs"]["error_tracking_backfill"] == "failed"
            with self.captureOnCommitCallbacks(execute=True):
                retried = self.client.post(f"{self.url}activate/", expected, format="json")
            assert retried.status_code == 200, retried.content
            assert launch.call_count == 4
            assert launch.call_args.args == (self.team.id, "error_tracking_backfill")
            activation.run("error_tracking_backfill")
            activation.run("error_tracking_backfill")
            assert temporal.start_workflow.await_count == 2
            config.refresh_from_db()
            assert config.onboarding is not None
            assert config.onboarding["jobs"]["error_tracking_backfill"] == "started"
            config.onboarding["jobs"]["error_tracking_backfill"] = "failed"
            config.save()
            activation.run("error_tracking_backfill")
            assert temporal.start_workflow.await_count == 3
            calls = temporal.start_workflow.call_args_list
            assert len({call.kwargs["id"] for call in calls}) == 1
            assert all(call.kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.REJECT_DUPLICATE for call in calls)
            config.refresh_from_db()
            assert config.onboarding is not None
            assert config.onboarding["jobs"]["error_tracking_backfill"] == "started"
            assert config.autostart_enabled is True
            general.refresh_from_db()
            assert not general.enabled
            assert set(SignalSourceConfig.objects.filter(team=self.team).values_list("pk", flat=True)) == source_ids

    @parameterized.expand([("github", "github_required"), ("quota", "quota_limited")])
    def test_quick_activation_preview_reports_repository_and_quota_blockers(self, failure: str, blocker: str) -> None:
        with (
            self._quick_activation_dependencies() as flags,
            patch.object(
                GitHubIntegration,
                "list_repositories",
                return_value=([] if failure == "github" else [{"full_name": "example/product"}], False),
            ),
            patch("products.signals.backend.quota.is_team_limited", return_value=failure == "quota"),
        ):
            flags["self-driving-quota-enforcement"] = True
            preview = self.client.get(f"{self.url}activation/")
        assert preview.status_code == 200, preview.content
        assert not preview.json()["can_activate"]
        assert blocker in {item["code"] for item in preview.json()["blockers"]}
        assert SignalTeamConfig.objects.get(team=self.team).onboarding is None
        assert not SignalScoutConfig.objects.for_team(self.team.id).exists()

    @parameterized.expand([("drained", "not_enrolled"), ("skipped", "not_enrolled"), ("withheld", "scout_unavailable")])
    def test_quick_activation_does_not_bypass_pilot_fleet_controls(self, control: str, blocker: str) -> None:
        payload: dict[str, object] = {"guaranteed_team_ids": ["*"]}
        if control == "drained":
            payload["guaranteed_team_ids"] = []
        elif control == "skipped":
            payload["skip_team_ids"] = [self.team.id]
        else:
            payload["default_team_config"] = {"withheld_skills": ["signals-scout-general"]}
        with (
            self._quick_activation_dependencies(pilot=True),
            patch("posthoganalytics.get_feature_flag_payload", return_value=payload),
        ):
            response = self.client.post(
                f"{self.url}activate/",
                {"expected_activation_mode": "github_optional", "expected_automatic_implementation": False},
                format="json",
            )
        assert response.status_code == 409, response.content
        assert blocker in {item["code"] for item in response.json()["blockers"]}
        assert not SignalScoutConfig.objects.for_team(self.team.id).exists()

    @parameterized.expand([(False,), (None,)])
    def test_quick_activation_requires_an_unchanged_policy(self, changed_ubp: bool | None) -> None:
        with self._quick_activation_dependencies() as flags:
            preview = self.client.get(f"{self.url}activation/")
            assert preview.status_code == 200 and preview.json()["can_activate"], preview.content
            flags["self-driving-ubp"] = changed_ubp
            response = self.client.post(
                f"{self.url}activate/",
                {"expected_activation_mode": "standard", "expected_automatic_implementation": False},
                format="json",
            )
        assert response.status_code == 409, response.content
        assert response.json()["error_code"] == "activation_changed"
        assert SignalTeamConfig.objects.get(team=self.team).onboarding is None
        assert not SignalScoutConfig.objects.for_team(self.team.id).exists()

    @parameterized.expand(
        [
            ("consent", "ai_consent_required"),
            ("draft", "setup_in_progress"),
            ("source", "sources_paused"),
            ("scout", "scout_paused"),
            ("edited_scout", "scout_customized"),
        ]
    )
    def test_quick_activation_preserves_unfinished_or_paused_setup(self, change: str, blocker: str) -> None:
        with self._quick_activation_dependencies():
            if change == "consent":
                self.organization.is_ai_data_processing_approved = False
                self.organization.save()
            elif change == "draft":
                config = SignalTeamConfig.objects.get(team=self.team)
                config.onboarding = {"draft": self.draft}
                config.save()
            elif change == "scout":
                seed_canonical_skills(self.team)
                SignalScoutConfig.objects.create(
                    team=self.team, skill_name="signals-scout-general", enabled=True, emit=True, lifecycle_locked=True
                )
            elif change == "edited_scout":
                seed_canonical_skills(self.team)
                edited = self.client.patch(
                    f"/api/projects/{self.team.id}/llm_skills/name/signals-scout-general",
                    {"body": "# Custom checkout investigation", "base_version": 1},
                    format="json",
                )
                assert edited.status_code == 200, edited.content
            else:
                self.source.enabled = False
                self.source.save()
                EventDefinition.objects.create(
                    team=self.team, project_id=self.team.project_id, name="$exception", last_seen_at=timezone.now()
                )
            before = SignalTeamConfig.objects.get(team=self.team).onboarding
            scouts_before = list(SignalScoutConfig.objects.for_team(self.team.id).values())
            response = self.client.post(
                f"{self.url}activate/",
                {"expected_activation_mode": "standard", "expected_automatic_implementation": False},
                format="json",
            )
        assert response.status_code == 409, response.content
        assert blocker in {item["code"] for item in response.json()["blockers"]}
        assert SignalTeamConfig.objects.get(team=self.team).onboarding == before
        assert list(SignalScoutConfig.objects.for_team(self.team.id).values()) == scouts_before

    def test_quick_activation_does_not_upgrade_a_read_only_credential(self) -> None:
        raw = self.create_personal_api_key_with_scopes(["task:read", "signal_scout:read"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        with self._quick_activation_dependencies():
            preview = self.client.get(f"{self.url}activation/")
            assert preview.status_code == 200, preview.content
            assert not preview.json()["can_activate"]
            response = self.client.post(
                f"{self.url}activate/",
                {"expected_activation_mode": "standard", "expected_automatic_implementation": False},
                format="json",
            )
        assert response.status_code == 403, response.content
        assert not SignalScoutConfig.objects.for_team(self.team.id).exists()

    @parameterized.expand([("scope",), ("object",)])
    def test_quick_activation_respects_replay_scanner_write_permissions(self, denial: str) -> None:
        scanner = ReplayScanner.objects.create(
            team=self.team, name="Checkout", created_by=self.user, enabled=True, emits_signals=False
        )
        if denial == "scope":
            raw = self.create_personal_api_key_with_scopes(
                ["task:write", "signal_scout:write", "llm_skill:write", "replay_scanner:read"]
            )
            self.client.logout()
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        else:
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save()
            member = User.objects.create_and_join(self.organization, "reviewer@example.com", "testtest")
            create_access_control(
                team_id=self.team.id, resource="replay_scanner", resource_id=str(scanner.id), access_level="viewer"
            )
            self.client.force_login(member)
        with self._quick_activation_dependencies():
            response = self.client.post(
                f"{self.url}activate/",
                {"expected_activation_mode": "standard", "expected_automatic_implementation": False},
                format="json",
            )
        assert response.status_code == 409, response.content
        assert "scanner_write_permission" in {item["code"] for item in response.json()["blockers"]}
        scanner.refresh_from_db()
        assert not scanner.emits_signals
        assert not SignalScoutConfig.objects.for_team(self.team.id).exists()
