from datetime import timedelta

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from celery.exceptions import Retry
from parameterized import parameterized
from requests import Timeout
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.transport.transport import EgressBudgetExhausted
from posthog.models import OAuthApplication
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.oauth import OAuthAccessToken
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.oauth_provenance import SANDBOX_OAUTH_APP_CLIENT_IDS

from products.signals.backend.models import (
    SignalFirstReportNotification,
    SignalScoutConfig,
    SignalScoutSuggestionSet,
    SignalSourceConfig,
    SignalTeamConfig,
)
from products.signals.backend.onboarding_activation import InboxOnboardingActivation
from products.signals.backend.onboarding_completion import InboxOnboardingReconciler
from products.signals.backend.scout_harness.config_registry import register_missing_configs
from products.signals.backend.scout_harness.lazy_seed import seed_canonical_skills
from products.signals.backend.tasks import launch_inbox_onboarding_job


class TestInboxOnboarding(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/signals/onboarding/"
        SignalTeamConfig.objects.get_or_create(team=self.team)
        self.source = SignalSourceConfig.objects.create(
            team=self.team, source_product="error_tracking", source_type="issue_created", enabled=True
        )
        self.scout_skill_name = "signals-scout-general"
        self.suggestion = {
            "id": "general",
            "kind": "canonical",
            "skill_name": self.scout_skill_name,
            "title": "General scout",
            "why_here": "Watch the product",
            "description": "",
            "draft_body": "",
            "proposed_config": {"run_interval_minutes": 1440, "emit": True},
            "gap": True,
            "confidence": "high",
        }
        self.draft = {
            "step": "github",
            "sources": [{"source_product": "error_tracking", "source_type": "issue_created", "enabled": True}],
            "scanner_ids": [],
            "suggestions": [],
            "automatic_implementation": False,
            "implementation_priority": "P1",
        }

    def test_draft_survives_reload_without_enabling_work(self) -> None:
        self.source.enabled = False
        self.source.save()
        response = self.client.post(self.url, self.draft, format="json")
        assert response.status_code == 200, response.json()
        assert self.client.get(self.url).json()["draft"] == self.draft
        self.source.refresh_from_db()
        assert self.source.enabled is False
        assert SignalTeamConfig.objects.get(team=self.team).autostart_enabled is None

    def test_exposure_is_recorded_once(self) -> None:
        with (
            patch("posthog.event_usage.posthoganalytics.capture") as capture,
            patch(
                "products.signals.backend.onboarding_analytics.posthoganalytics.feature_enabled", return_value=True
            ) as flag,
            self.captureOnCommitCallbacks(execute=True),
        ):
            first = self.client.post(f"{self.url}expose/")
            second = self.client.post(f"{self.url}expose/")
        assert first.status_code == 200, first.json()
        assert first.json() == second.json()
        assert capture.call_count == 1
        assert capture.call_args.kwargs["properties"]["setup_mode"] is None
        assert capture.call_args.kwargs["properties"]["self_driving_ubp"] is True
        state = SignalTeamConfig.objects.get(team=self.team).onboarding
        assert state is not None
        assert state["exposed_by"] == self.user.pk
        assert "variant" not in state
        assert capture.call_args.kwargs["properties"]["$set_once"] == {"email": self.user.email}
        assert capture.call_args.kwargs["groups"]["project"] == str(self.team.uuid)
        assert capture.call_args.kwargs["groups"]["organization"] == str(self.organization.id)
        assert flag.call_args.args == ("self-driving-ubp", str(self.user.distinct_id))
        assert flag.call_args.kwargs["groups"]["organization"] == str(self.organization.id)

    @parameterized.expand(
        [
            ("github",),
            ("source",),
            ("disabled_source",),
            ("scanner",),
            ("empty",),
        ]
    )
    def test_incomplete_setup_never_converts(self, missing: str) -> None:
        if missing == "source":
            self.source.enabled = False
            self.source.save()
        if missing == "disabled_source":
            self.draft["sources"] = [
                {"source_product": "error_tracking", "source_type": "issue_created", "enabled": False}
            ]
        if missing == "scanner":
            self.draft["scanner_ids"] = ["11111111-1111-4111-8111-111111111111"]
        if missing == "empty":
            self.draft["sources"] = []
        with patch(
            "products.signals.backend.onboarding_completion.InboxOnboardingReconciler.has_repository",
            return_value=None if missing == "github" else object(),
        ):
            response = self.client.post(f"{self.url}complete/", self.draft, format="json")
        assert response.status_code == 400, response.json()
        assert not (SignalTeamConfig.objects.get(team=self.team).onboarding or {}).get("completed_at")

    @parameterized.expand(
        [
            (None, False, None),
            ("guided", False, None),
            ("guided", False, "test-sol"),
            ("guided", False, "control"),
            ("quick", False, None),
            ("quick", True, "test-sol"),
        ]
    )
    def test_completion_is_durable_and_retry_safe(
        self, setup_mode: str | None, automatic_implementation: bool, arm: str | None
    ) -> None:
        self.draft["automatic_implementation"] = automatic_implementation
        if setup_mode:
            self.draft["setup_mode"] = setup_mode
        quick = setup_mode == "quick"
        has_scout = quick and automatic_implementation
        if has_scout:
            self.draft["suggestions"] = [self.suggestion]
            SignalScoutConfig.objects.create(team=self.team, skill_name=self.scout_skill_name, enabled=True, emit=True)
        with (
            patch(
                "products.signals.backend.onboarding_completion.InboxOnboardingReconciler.has_repository",
                return_value=object(),
            ),
            patch("posthog.event_usage.posthoganalytics.capture") as capture,
            patch(
                "products.signals.backend.onboarding_analytics.posthoganalytics.feature_enabled",
                return_value=not automatic_implementation,
            ),
            patch("products.signals.backend.tasks.launch_inbox_onboarding_job.delay") as launch,
            patch(
                "products.signals.backend.first_report_experiment.posthoganalytics.get_feature_flag",
                return_value=arm or False,
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            first = self.client.post(f"{self.url}complete/", self.draft, format="json")
            second = self.client.post(f"{self.url}complete/", self.draft, format="json")
        assert first.status_code == 200, first.json()
        assert first.json() == second.json()
        config = SignalTeamConfig.objects.get(team=self.team)
        assert config.onboarding is not None
        assert config.onboarding["jobs"] == {
            "scout": "pending" if arm or quick else "skipped",
            "recommendations": "pending" if quick else "skipped",
        }
        pending_jobs = {job for job, status in config.onboarding["jobs"].items() if status == "pending"}
        assert {call.args for call in launch.call_args_list} == {(self.team.id, job) for job in pending_jobs}
        assert config.onboarding.get("first_report_variant") == arm
        assert bool(first.json().get("first_report")) is (arm == "test-sol")
        assert config.autostart_enabled is automatic_implementation
        assert config.default_autostart_priority == "P1"
        assert config.onboarding["activated_by"] == self.user.id
        notification = SignalFirstReportNotification.objects.for_team(self.team.id).get()
        assert notification.activated_by_id == self.user.id
        assert notification.queued_at is None
        assert capture.call_args.kwargs["properties"] == {
            "$set_once": {"email": self.user.email},
            "project_id": self.team.id,
            "flow_version": "ui-first-v1",
            "inbox_client": "cloud",
            "setup_mode": setup_mode or "guided",
            "self_driving_ubp": not automatic_implementation,
            "automatic_implementation": automatic_implementation,
            "implementation_priority": "P1",
            "enabled_source_products": ["error_tracking", "signals_scout"] if has_scout else ["error_tracking"],
            "scout_count": 1 if has_scout else 0,
        }
        assert (
            len(
                [
                    call
                    for call in capture.call_args_list
                    if call.kwargs.get("event") == "self-driving onboarding completed"
                ]
            )
            == 1
        )

    @parameterized.expand(
        [
            (False, False, 400, False),
            (True, True, 400, False),
            (True, False, 200, False),
            (True, False, 200, True),
            (True, False, 403, True, False),
        ]
    )
    def test_pilot_activation_requires_eligibility_and_keeps_implementation_off(
        self, eligible: bool, automatic: bool, status: int, child_environment: bool, parent_task_editor: bool = True
    ) -> None:
        self.draft.update(
            activation_mode="github_optional", automatic_implementation=automatic, suggestions=[self.suggestion]
        )
        SignalScoutConfig.objects.create(team=self.team, skill_name=self.scout_skill_name, enabled=True, emit=True)
        activation_team = self.team
        if child_environment:
            activation_team = Team.objects.create(organization=self.organization, parent_team=self.team)
            SignalSourceConfig.objects.create(
                team=activation_team, source_product="error_tracking", source_type="issue_created", enabled=True
            )
        config, _ = SignalTeamConfig.objects.get_or_create(team=activation_team)
        config.onboarding = {"variant": "control"}
        config.save()
        with (
            patch("products.signals.backend.github_optional.ResearchAccessPolicy.enabled", return_value=eligible),
            patch("products.signals.backend.facade.onboarding.UserAccessControl") as parent_access,
            patch.object(
                InboxOnboardingReconciler,
                "has_repository",
                side_effect=AssertionError("Pilot must not depend on GitHub"),
            ),
            patch("products.signals.backend.tasks.launch_inbox_onboarding_job.delay") as launch,
            self.captureOnCommitCallbacks(execute=True),
        ):
            parent_access.return_value.check_access_level_for_resource.return_value = parent_task_editor
            response = self.client.post(
                f"/api/projects/{activation_team.id}/signals/onboarding/complete/", self.draft, format="json"
            )
        assert response.status_code == status, response.json()
        if child_environment and eligible and not automatic:
            parent_access.assert_called_once_with(user=self.user, team=self.team)
            parent_access.return_value.check_access_level_for_resource.assert_called_once_with("task", "editor")
        config.refresh_from_db()
        assert config.onboarding["variant"] == "control"
        if status == 200:
            assert config.autostart_enabled is False
            assert SignalTeamConfig.objects.get(team=self.team).autostart_enabled is False
            assert config.onboarding["completed_at"]
            assert config.onboarding["jobs"] == {"scout": "pending", "recommendations": "pending"}
            assert {call.args for call in launch.call_args_list} == {
                (activation_team.id, "scout"),
                (activation_team.id, "recommendations"),
            }
        else:
            assert not config.onboarding.get("completed_at")
            launch.assert_not_called()

    def test_completed_quick_activation_checks_scout_write_access_before_retrying_jobs(self) -> None:
        self.draft["suggestions"] = [self.suggestion]
        config = SignalTeamConfig.objects.get(team=self.team)
        config.onboarding = {
            "completed_at": timezone.now().isoformat(),
            "draft": self.draft,
            "jobs": {"scout": "failed", "recommendations": "failed"},
        }
        config.save()
        raw = self.create_personal_api_key_with_scopes(["task:write", "signal_scout:read"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        with patch("products.signals.backend.tasks.launch_inbox_onboarding_job.delay") as launch:
            response = self.client.post(f"{self.url}complete/", self.draft, format="json")
        assert response.status_code == 403, response.json()
        launch.assert_not_called()

    @parameterized.expand([(None,), (True,), (False,)])
    def test_scout_only_completion_respects_source_gate(self, enabled: bool | None) -> None:
        self.source.enabled = False
        self.source.save()
        self.draft["sources"] = []
        self.draft["suggestions"] = [self.suggestion]
        SignalScoutConfig.objects.create(team=self.team, skill_name=self.scout_skill_name, enabled=True, emit=True)
        if enabled is not None:
            SignalSourceConfig.objects.create(
                team=self.team, source_product="signals_scout", source_type="cross_source_issue", enabled=enabled
            )
        Integration.objects.create(team=self.team, kind="github")
        with patch.object(
            GitHubIntegration, "list_repositories", return_value=([{"full_name": "example/product"}], False)
        ):
            response = self.client.post(f"{self.url}complete/", self.draft, format="json")
        assert response.status_code == (400 if enabled is False else 200), response.json()
        config = SignalTeamConfig.objects.get(team=self.team)
        assert bool((config.onboarding or {}).get("completed_at")) is (enabled is not False)

    @parameterized.expand(
        [
            (False, "scout", 403),
            (True, "scout", 200),
            (False, "source", 403),
            (True, "source", 200),
            (False, "none", 403),
            (True, "none", 200),
        ]
    )
    def test_child_completion_checks_parent_scout_access(
        self, parent_access: bool, selection: str, expected_status: int
    ) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        SignalTeamConfig.objects.create(team=child)
        SignalSourceConfig.objects.create(
            team=child, source_product="error_tracking", source_type="issue_created", enabled=True
        )
        SignalScoutConfig.objects.create(team=self.team, skill_name=self.scout_skill_name)
        Integration.objects.create(team=child, kind="github")
        if selection == "scout":
            self.draft["suggestions"] = [self.suggestion]
        elif selection == "source":
            SignalSourceConfig.objects.create(
                team=self.team, source_product="signals_scout", source_type="cross_source_issue", enabled=True
            )
            self.draft["sources"] = [
                {"source_product": "signals_scout", "source_type": "cross_source_issue", "enabled": True}
            ]
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="onboarding",
            user=self.user,
            secure_value=hash_key_value(raw),
            scopes=["task:write", "signal_scout:write", "llm_skill:write"],
            scoped_teams=[child.id, self.team.id] if parent_access else [child.id],
        )
        self.client.logout()
        with patch.object(
            GitHubIntegration, "list_repositories", return_value=([{"full_name": "example/product"}], False)
        ):
            response = self.client.post(
                f"/api/projects/{child.id}/signals/onboarding/complete/",
                self.draft,
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {raw}",
            )
        assert response.status_code == expected_status, response.content

    @parameterized.expand([("",), ("complete/",), ("expose/",)])
    def test_onboarding_writes_require_a_non_sandbox_credential(self, action: str) -> None:
        application = OAuthApplication.objects.create(
            client_id=sorted(SANDBOX_OAUTH_APP_CLIENT_IDS)[0],
            name="Onboarding test",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm=OAuthApplication.RS256_ALGORITHM,
        )
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token="pha_onboarding_test_token",
            scope="task:read task:write internal_run:read",
            expires=timezone.now() + timedelta(hours=1),
            scoped_teams=[self.team.id],
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        response = self.client.post(f"{self.url}{action}", self.draft, format="json")
        assert response.status_code == 403, response.content
        assert self.client.get(self.url).status_code == 200
        assert SignalTeamConfig.objects.get(team=self.team).onboarding is None

    def test_onboarding_activity_masks_scout_drafts(self) -> None:
        self.draft["suggestions"] = [{**self.suggestion, "draft_body": "Investigate example checkout errors."}]
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url, self.draft, format="json")
        assert response.status_code == 200, response.content
        log = ActivityLog.objects.filter(team_id=self.team.id, scope="SignalTeamConfig").latest("created_at")
        assert log.detail is not None
        change = next(change for change in log.detail["changes"] if change["field"] == "onboarding")
        assert change["after"] == "masked"
        change["after"] = {"draft": self.draft}
        safe_detail = log.safe_detail
        assert safe_detail is not None
        assert next(change for change in safe_detail["changes"] if change["field"] == "onboarding")["after"] == "masked"

    @parameterized.expand([("unchanged", True), ("user_paused", False), ("withheld", False), ("task_only", False)])
    def test_activation_resumes_only_onboarding_operational_pauses(self, state: str, enabled: bool) -> None:
        seed_canonical_skills(self.team)
        register_missing_configs(self.team.id, enable_new_configs=False)
        scout = SignalScoutConfig.objects.for_team(self.team.id).get(skill_name="signals-scout-inbox-validation")
        register_missing_configs(self.team.id)
        scout.refresh_from_db()
        assert not scout.enabled
        if state == "user_paused":
            scout.status_changed_at = timezone.now() + timedelta(seconds=1)
            scout.save(update_fields=["status_changed_at"])
        withheld = [scout.skill_name] if state == "withheld" else []
        if state == "task_only":
            raw = self.create_personal_api_key_with_scopes(["task:write"])
            self.client.logout()
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        with (
            patch.object(
                GitHubIntegration, "list_repositories", return_value=([{"full_name": "example/product"}], False)
            ),
            patch(
                "products.signals.backend.scout_harness.team_limits.posthoganalytics.get_feature_flag_payload",
                return_value={"default_team_config": {"withheld_skills": withheld}},
            ),
        ):
            Integration.objects.create(team=self.team, kind="github")
            response = self.client.post(f"{self.url}complete/", self.draft, format="json")
        assert response.status_code == (403 if state == "task_only" else 200), response.content
        scout.refresh_from_db()
        assert scout.enabled is enabled
        assert not SignalScoutConfig.objects.for_team(self.team.id).get(skill_name="signals-scout-general").enabled
        if state == "task_only":
            onboarding = SignalTeamConfig.objects.get(team=self.team).onboarding
            assert onboarding is not None
            assert not onboarding.get("completed_at")
        elif state == "withheld":
            register_missing_configs(self.team.id, withheld_skill_names=set(withheld))
            scout.refresh_from_db()
            assert not scout.enabled
            register_missing_configs(self.team.id, withheld_skill_names=set())
            scout.refresh_from_db()
            assert scout.enabled

    @parameterized.expand([("expose",), ("read",)])
    def test_child_scoped_credential_cannot_access_parent_onboarding(self, action: str) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="onboarding",
            user=self.user,
            secure_value=hash_key_value(raw),
            scopes=["task:write", "signal_scout:read"],
            scoped_teams=[child.id],
        )
        self.client.logout()
        response = (
            self.client.get(f"/api/projects/{child.id}/signals/onboarding/", HTTP_AUTHORIZATION=f"Bearer {raw}")
            if action == "read"
            else self.client.post(
                f"/api/projects/{child.id}/signals/onboarding/{action}/", HTTP_AUTHORIZATION=f"Bearer {raw}"
            )
        )
        assert response.status_code == 403, response.content

    @parameterized.expand(
        [
            (GitHubIntegrationError, True),
            (GitHubRateLimitError, True),
            (EgressBudgetExhausted, True),
            (Timeout, True),
            (GitHubRateLimitError, False),
        ]
    )
    def test_repository_discovery_continues_after_failure(self, error: type[Exception], healthy: bool) -> None:
        Integration.objects.create(team=self.team, kind="github")
        Integration.objects.create(team=self.team, kind="github")
        result = ([{"full_name": "example/product"}], True) if healthy else ([], False)
        with patch.object(
            GitHubIntegration, "list_repositories", side_effect=[error("unavailable"), result]
        ) as listing:
            response = self.client.post(f"{self.url}complete/", self.draft, format="json")
        assert response.status_code == (200 if healthy else 503), response.content
        assert listing.call_count == 2
        assert all(call.kwargs == {"per_page": 1} for call in listing.call_args_list)

    @parameterized.expand(
        [
            ("get", ["task:read"], True, 403),
            ("get", ["task:read"], False, 200),
            ("get", ["task:read", "signal_scout:read"], True, 200),
            ("post", ["task:write"], True, 403),
            ("post", ["task:write", "signal_scout:write"], True, 403),
            ("post", ["task:write", "signal_scout:write", "llm_skill:write"], True, 200),
            ("post", ["task:write"], False, 200),
        ]
    )
    def test_draft_scout_permissions(
        self, method: str, scopes: list[str], with_scout: bool, expected_status: int
    ) -> None:
        if with_scout:
            self.draft["suggestions"] = [{**self.suggestion, "kind": "custom", "draft_body": "Watch failed upgrades."}]
        config = SignalTeamConfig.objects.get(team=self.team)
        if method == "get":
            config.onboarding = {"draft": self.draft}
            config.save()
        raw = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        response = (
            self.client.get(self.url) if method == "get" else self.client.post(self.url, self.draft, format="json")
        )
        assert response.status_code == expected_status, response.content
        if method == "post" and expected_status == 403:
            config.refresh_from_db()
            assert config.onboarding is None

    @parameterized.expand([("suggestions",), ("activation_scouts",)])
    def test_task_only_writer_cannot_clear_existing_scout_choices(self, field: str) -> None:
        config = SignalTeamConfig.objects.get(team=self.team)
        original = [self.suggestion] if field == "suggestions" else [self.scout_skill_name]
        config.onboarding = {"draft": {**self.draft, field: original}}
        config.save()
        raw = self.create_personal_api_key_with_scopes(["task:write"])
        self.client.logout()
        response = self.client.post(self.url, self.draft, format="json", HTTP_AUTHORIZATION=f"Bearer {raw}")
        assert response.status_code == 403, response.content
        config.refresh_from_db()
        assert config.onboarding["draft"][field] == original

    @parameterized.expand(
        [
            (False, -60, -30, "started"),
            (False, 1, 2, "failed"),
            (False, 1, -1, "started"),
            (True, 1, 2, "failed"),
        ]
    )
    def test_activation_state_reports_only_current_recommendation_failure(
        self, child_project: bool, requested_offset: int, finished_offset: int, expected_status: str
    ) -> None:
        team = (
            Team.objects.create(organization=self.organization, parent_team=self.team) if child_project else self.team
        )
        activated_at = timezone.now()
        config, _ = SignalTeamConfig.objects.get_or_create(team=team)
        config.onboarding = {
            "completed_at": activated_at.isoformat(),
            "jobs": {"scout": "started", "recommendations": "started"},
        }
        config.save()
        SignalScoutSuggestionSet.objects.create(
            team=self.team,
            status=SignalScoutSuggestionSet.Status.FAILED,
            generated_at=activated_at - timedelta(days=1),
            last_requested_at=activated_at + timedelta(seconds=requested_offset),
            last_completed_at=activated_at + timedelta(seconds=finished_offset),
        )
        response = self.client.get(f"/api/projects/{team.id}/signals/onboarding/")
        assert response.status_code == 200, response.content
        assert response.json()["jobs"] == {"scout": "started", "recommendations": expected_status}
        config.refresh_from_db()
        assert config.onboarding["jobs"]["recommendations"] == "started"


class TestInboxOnboardingActivation(BaseTest):
    @parameterized.expand([(False, True), (True, True), (False, False), (False, True, False)])
    def test_scout_dispatch_requires_data_and_eligibility(
        self, first_probe_fails: bool, enrolled: bool, source_enabled: bool = True
    ) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        if not source_enabled:
            SignalSourceConfig.objects.create(
                team=self.team, source_product="signals_scout", source_type="cross_source_issue", enabled=False
            )
        config = SignalTeamConfig.objects.create(
            team=self.team,
            onboarding={
                "first_report_variant": "test-sol",
                "completed_at": timezone.now().isoformat(),
                "activated_by": self.user.pk,
                "jobs": {"scout": "pending"},
            },
        )
        with (
            patch("products.signals.backend.onboarding_activation.ph_scoped_capture") as capture,
            self.captureOnCommitCallbacks(execute=True),
            patch(
                "products.signals.backend.scout_harness.profile.builders.execute_hogql_query",
                return_value=MagicMock(results=[["$pageview", 100, 10, 20, 5, timezone.now(), timezone.now()]]),
            ),
            patch(
                "products.signals.backend.first_report_scout.execute_hogql_query",
                side_effect=lambda **kwargs: MagicMock(results=[[0, None]] if len(kwargs["query"].select) == 2 else []),
            ) as probe,
            patch("products.signals.backend.onboarding_activation.sync_connect") as connect,
            patch(
                "products.signals.backend.first_report_experiment.posthoganalytics.get_feature_flag",
                return_value="test-sol" if enrolled else False,
            ),
            patch(
                "posthoganalytics.get_feature_flag_payload",
                return_value={"enabled": True, "guaranteed_team_ids": [self.team.id]},
            ),
        ):
            if first_probe_fails:
                healthy_probe = probe.side_effect
                probe.side_effect = RuntimeError("Query unavailable")
                with self.assertRaisesRegex(RuntimeError, "data availability is unknown"):
                    InboxOnboardingActivation(self.team.id).run("scout", final_attempt=False)
                config.refresh_from_db()
                assert config.onboarding is not None
                assert config.onboarding["jobs"]["scout"] == "pending"
                probe.side_effect = healthy_probe
            InboxOnboardingActivation(self.team.id).run("scout")
        connect.assert_not_called()
        config.refresh_from_db()
        assert config.onboarding is not None
        assert config.onboarding["first_report"]["status"] == (
            "no_data" if enrolled and source_enabled else "incomplete"
        )
        assert (
            capture.return_value.__enter__.return_value.call_args.kwargs["properties"]["first_report_outcome"]
            == config.onboarding["first_report"]["status"]
        )
        if not enrolled or not source_enabled:
            probe.assert_not_called()
        assert (
            not SignalScoutConfig.objects.for_team(self.team.id)
            .filter(skill_name="signals-scout-first-report")
            .exists()
        )

    @parameterized.expand(
        [
            ("scout", 0, None),
            ("scout", 5, None),
            ("scout", 0, "test-sol"),
            ("scout", 5, "test-sol"),
            ("scout", 0, "control"),
            ("scout", 0, "test-sol", "flag_error"),
            ("scout", 5, "test-sol", "flag_error"),
            ("scout", 0, "test-sol", "flag_missing"),
            ("scout", 5, "test-sol", "flag_missing"),
            ("recommendations", 0, "test-sol"),
            ("recommendations", 5, "test-sol"),
            ("scout", 0, None, "workflow", True),
            ("recommendations", 0, None, "workflow", True),
        ]
    )
    def test_dispatch_retries_use_one_workflow_and_preserve_completed_jobs(
        self, job: str, retry_count: int, arm: str | None, failure_source: str = "workflow", pilot: bool = False
    ) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        config = SignalTeamConfig.objects.create(
            team=self.team,
            onboarding={
                "draft": {"activation_mode": "github_optional"} if pilot else {"setup_mode": "quick"},
                "first_report_variant": arm,
                "completed_at": timezone.now().isoformat(),
                "activated_by": self.user.pk,
                "jobs": {"scout": "pending", "recommendations": "pending"},
            },
        )
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-general", enabled=True, emit=True)
        client = MagicMock()
        client.start_workflow = AsyncMock()
        with (
            patch("products.signals.backend.onboarding_activation.sync_connect", return_value=client),
            patch(
                "products.signals.backend.first_report_experiment.posthoganalytics.get_feature_flag",
                return_value=arm or False,
            ) as flag,
            patch("products.signals.backend.first_report_experiment.ph_scoped_capture") as exposure,
            patch(
                "products.signals.backend.scout_harness.profile.builders.execute_hogql_query",
                return_value=MagicMock(results=[["$pageview", 100, 10, 20, 5, timezone.now(), timezone.now()]]),
            ),
            patch(
                "products.signals.backend.first_report_scout.execute_hogql_query",
                return_value=MagicMock(results=[[100, timezone.now()]]),
            ),
            patch("products.signals.backend.onboarding_activation.ph_scoped_capture") as capture,
            patch("products.signals.backend.onboarding_analytics.posthoganalytics.feature_enabled", return_value=True),
            self.captureOnCommitCallbacks(execute=True),
            patch("products.signals.backend.temporal.agentic.scout_suggestions.stamp_requested"),
            patch(
                "posthoganalytics.get_feature_flag_payload",
                return_value={"enabled": True, "guaranteed_team_ids": [self.team.id]},
            ),
        ):
            if failure_source == "flag_error":
                flag.side_effect = RuntimeError("Flag evaluation unavailable")
            elif failure_source == "flag_missing":
                flag.return_value = None
            else:
                client.start_workflow.side_effect = RuntimeError("Temporarily unavailable")
            launch_inbox_onboarding_job.push_request(retries=retry_count)
            try:
                with patch.object(launch_inbox_onboarding_job, "retry", side_effect=Retry()), self.assertRaises(Retry):
                    launch_inbox_onboarding_job.run(self.team.id, job)
            finally:
                launch_inbox_onboarding_job.pop_request()
            config.refresh_from_db()
            assert config.onboarding is not None
            assert config.onboarding["jobs"][job] == ("failed" if retry_count == 5 else "pending")
            if job == "scout" and arm == "test-sol" and failure_source == "workflow":
                assert config.onboarding["first_report_activation_team_id"] == self.team.id
            if failure_source != "workflow":
                client.start_workflow.assert_not_called()
                if retry_count == 5:
                    assert config.onboarding["first_report"]["status"] == "incomplete"
            flag.side_effect = None
            flag.return_value = arm or False
            client.start_workflow.reset_mock(side_effect=True)
            activation = InboxOnboardingActivation(self.team.id)
            activation.run(job)
            activation.run(job)
            client.start_workflow.assert_awaited_once()
            dispatch = client.start_workflow.call_args.kwargs
            assert dispatch["id_reuse_policy"] == WorkflowIDReusePolicy.REJECT_DUPLICATE
            config.refresh_from_db()
            assert config.onboarding is not None
            assert config.onboarding["jobs"][job] == "started"
            config.onboarding["jobs"][job] = "pending"
            config.save()
            client.start_workflow.side_effect = WorkflowAlreadyStartedError(dispatch["id"], "workflow")
            activation.run(job)
        config.refresh_from_db()
        assert config.onboarding is not None
        assert config.onboarding["jobs"][job] == "started"
        assert client.start_workflow.call_args.kwargs["id"] == dispatch["id"]
        if job == "scout":
            started_skill = client.start_workflow.call_args.args[1].skill_name
            assert started_skill == ("signals-scout-first-report" if arm == "test-sol" else "signals-scout-general")
            exposures = exposure.return_value.__enter__.return_value.call_args_list
            assert {event.kwargs["properties"]["$feature_flag_response"] for event in exposures} == (
                {arm} if arm else set()
            )
        assert SignalScoutConfig.objects.for_team(self.team.id).filter(
            skill_name="signals-scout-first-report"
        ).exists() is (job == "scout" and arm == "test-sol")
        events = capture.return_value.__enter__.return_value.call_args_list
        assert [event.kwargs["properties"]["status"] for event in events] == (
            ["failed", "started", "started"] if retry_count == 5 else ["started", "started"]
        )
        assert all(event.kwargs["event"] == "self-driving onboarding job status changed" for event in events)
        assert all(event.kwargs["properties"]["job"] == job for event in events)
        assert all(event.kwargs["properties"]["setup_mode"] == "quick" for event in events)

    @parameterized.expand([("scout",), ("recommendations",)])
    def test_no_background_work_without_ai_consent(self, job: str) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        config = SignalTeamConfig.objects.create(
            team=self.team,
            onboarding={
                "completed_at": timezone.now().isoformat(),
                "jobs": {"scout": "pending", "recommendations": "pending"},
            },
        )
        with (
            patch("products.signals.backend.onboarding_activation.sync_connect") as connect,
            patch("products.signals.backend.onboarding_activation.ph_scoped_capture") as capture,
            patch("products.signals.backend.onboarding_analytics.posthoganalytics.feature_enabled", return_value=None),
            self.captureOnCommitCallbacks(execute=True),
        ):
            InboxOnboardingActivation(self.team.id).run(job)
        connect.assert_not_called()
        config.refresh_from_db()
        assert config.onboarding is not None
        assert config.onboarding["jobs"][job] == "skipped"
        capture.return_value.__enter__.return_value.assert_called_once()
        assert (
            capture.return_value.__enter__.return_value.call_args.kwargs["properties"]["reason"]
            == "ai_consent_required"
        )
