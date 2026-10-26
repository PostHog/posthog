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
from products.signals.backend.tasks import launch_inbox_onboarding_job, reconcile_inbox_onboarding


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

    @parameterized.expand([("control",), ("test-ui",), ("test-github",)])
    def test_exposure_is_sticky_and_queued_once(self, variant: str) -> None:
        with (
            patch("posthog.event_usage.posthoganalytics.capture") as capture,
            patch(
                "products.signals.backend.onboarding_analytics.posthoganalytics.feature_enabled", return_value=True
            ) as flag,
            patch("products.signals.backend.tasks.reconcile_inbox_onboarding.delay") as reconcile,
            self.captureOnCommitCallbacks(execute=True),
        ):
            first = self.client.post(f"{self.url}expose/", {"variant": variant}, format="json")
            second = self.client.post(
                f"{self.url}expose/", {"variant": "test-ui" if variant == "control" else "control"}, format="json"
            )
        assert first.status_code == 200
        assert first.json()["variant"] == variant
        assert second.json()["variant"] == variant
        assert capture.call_count == 1
        assert capture.call_args.kwargs["properties"]["variant"] == variant
        assert capture.call_args.kwargs["properties"]["$feature/inbox-ui-onboarding"] == variant
        assert capture.call_args.kwargs["properties"]["self_driving_ubp"] is True
        assert capture.call_args.kwargs["properties"]["$set_once"] == {"email": self.user.email}
        assert capture.call_args.kwargs["groups"]["project"] == str(self.team.uuid)
        assert capture.call_args.kwargs["groups"]["organization"] == str(self.organization.id)
        assert flag.call_args.args == ("self-driving-ubp", str(self.user.distinct_id))
        assert flag.call_args.kwargs["groups"]["organization"] == str(self.organization.id)
        if variant == "control":
            reconcile.assert_called_once_with(self.team.id)
        else:
            reconcile.assert_not_called()

    def test_control_completion_is_verified_without_a_browser_and_only_once(self) -> None:
        config = SignalTeamConfig.objects.get(team=self.team)
        config.onboarding = {"variant": "control", "exposed_at": timezone.now().isoformat(), "exposed_by": self.user.pk}
        config.save()
        with (
            patch.object(InboxOnboardingReconciler, "has_repository", return_value=False) as repository,
            patch("products.signals.backend.onboarding_completion.ph_scoped_capture") as capture,
            patch(
                "products.signals.backend.onboarding_analytics.posthoganalytics.feature_enabled",
                side_effect=RuntimeError("Unavailable"),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            assert InboxOnboardingReconciler(self.team.id).run() is True
            config.refresh_from_db()
            assert not config.onboarding.get("completed_at")
            repository.return_value = True
            assert InboxOnboardingReconciler(self.team.id).run() is False
            assert InboxOnboardingReconciler(self.team.id).run() is False
        config.refresh_from_db()
        assert config.onboarding["completed_at"]
        capture.assert_called_once()
        assert capture.return_value.__enter__.return_value.call_args.kwargs["properties"]["variant"] == "control"
        assert capture.return_value.__enter__.return_value.call_args.kwargs["properties"]["self_driving_ubp"] is None
        assert capture.return_value.__enter__.return_value.call_args.kwargs["properties"]["setup_mode"] == "legacy"

    @parameterized.expand([(False,), (True,)])
    def test_control_reconciliation_waits_for_manual_activation(self, draft_saved_during_check: bool) -> None:
        config = SignalTeamConfig.objects.get(team=self.team)
        config.onboarding = {"variant": "control", "exposed_at": timezone.now().isoformat()}
        if not draft_saved_during_check:
            config.onboarding["draft"] = self.draft
        config.save()

        def save_draft_and_return_repository() -> bool:
            config.onboarding = {**(config.onboarding or {}), "draft": self.draft}
            config.save()
            return True

        with (
            patch.object(InboxOnboardingReconciler, "has_repository", side_effect=save_draft_and_return_repository),
            patch("products.signals.backend.onboarding_completion.ph_scoped_capture") as capture,
            self.captureOnCommitCallbacks(execute=True),
        ):
            assert InboxOnboardingReconciler(self.team.id).run() is False
        config.refresh_from_db()
        assert not config.onboarding.get("completed_at")
        capture.assert_not_called()

    def test_control_without_a_source_never_converts(self) -> None:
        config = SignalTeamConfig.objects.get(team=self.team)
        config.onboarding = {"variant": "control", "exposed_at": timezone.now().isoformat()}
        config.save()
        self.source.enabled = False
        self.source.save()
        with patch.object(InboxOnboardingReconciler, "has_repository", return_value=True):
            assert InboxOnboardingReconciler(self.team.id).run() is True
        config.refresh_from_db()
        assert not config.onboarding.get("completed_at")

    @parameterized.expand(
        [
            ("github",),
            ("source",),
            ("disabled_source",),
            ("scanner",),
            ("empty",),
            ("quick_scout",),
        ]
    )
    def test_incomplete_setup_never_converts(self, missing: str) -> None:
        if missing.startswith("quick_"):
            config = SignalTeamConfig.objects.get(team=self.team)
            config.onboarding = {"variant": "test-github"}
            config.save()
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
        [(None, False), ("control", False), ("test-ui", False), ("test-github", False), ("test-github", True)]
    )
    def test_completion_is_durable_and_retry_safe(self, variant: str | None, automatic_implementation: bool) -> None:
        self.draft["automatic_implementation"] = automatic_implementation
        if variant == "test-github":
            self.draft["suggestions"] = [self.suggestion]
            SignalScoutConfig.objects.create(team=self.team, skill_name=self.scout_skill_name, enabled=True, emit=True)
        config = SignalTeamConfig.objects.get(team=self.team)
        config.onboarding = {"variant": variant}
        config.save()
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
            self.captureOnCommitCallbacks(execute=True),
        ):
            first = self.client.post(f"{self.url}complete/", self.draft, format="json")
            second = self.client.post(f"{self.url}complete/", self.draft, format="json")
        assert first.status_code == 200, first.json()
        assert first.json() == second.json()
        config = SignalTeamConfig.objects.get(team=self.team)
        assert config.onboarding is not None
        if variant == "test-github":
            assert config.onboarding["jobs"] == {"scout": "pending", "recommendations": "pending"}
            assert {call.args for call in launch.call_args_list} == {
                (self.team.id, "scout"),
                (self.team.id, "recommendations"),
            }
        else:
            launch.assert_not_called()
        assert config.autostart_enabled is automatic_implementation
        assert config.default_autostart_priority == "P1"
        assert config.onboarding["activated_by"] == self.user.id
        notification = SignalFirstReportNotification.objects.for_team(self.team.id).get()
        assert notification.activated_by_id == self.user.id
        assert notification.queued_at is None
        assert capture.call_args.kwargs["properties"]["variant"] == variant
        assert capture.call_args.kwargs["properties"] == {
            "$set_once": {"email": self.user.email},
            "variant": variant,
            "$feature/inbox-ui-onboarding": variant,
            "project_id": self.team.id,
            "flow_version": "ui-first-v1",
            "inbox_client": "cloud",
            "setup_mode": "quick" if variant == "test-github" else "guided",
            "self_driving_ubp": not automatic_implementation,
            "automatic_implementation": automatic_implementation,
            "implementation_priority": "P1",
            "enabled_source_products": ["error_tracking", "signals_scout"]
            if variant == "test-github"
            else ["error_tracking"],
            "scout_count": 1 if variant == "test-github" else 0,
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

    def test_completed_quick_activation_checks_scout_write_access_before_retrying_jobs(self) -> None:
        self.draft["suggestions"] = [self.suggestion]
        config = SignalTeamConfig.objects.get(team=self.team)
        config.onboarding = {
            "variant": "test-github",
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

    @parameterized.expand([(None, False), (True, False), (False, False), (None, True), (False, True)])
    def test_scout_only_completion_respects_source_gate(self, enabled: bool | None, control: bool) -> None:
        self.source.enabled = False
        self.source.save()
        self.draft["sources"] = []
        self.draft["suggestions"] = [self.suggestion]
        SignalScoutConfig.objects.create(team=self.team, skill_name=self.scout_skill_name, enabled=True, emit=True)
        if enabled is not None:
            SignalSourceConfig.objects.create(
                team=self.team, source_product="signals_scout", source_type="cross_source_issue", enabled=enabled
            )
        config = SignalTeamConfig.objects.get(team=self.team)
        if control:
            config.onboarding = {"variant": "control", "exposed_at": timezone.now().isoformat()}
            config.save()
        Integration.objects.create(team=self.team, kind="github")
        with patch.object(
            GitHubIntegration, "list_repositories", return_value=([{"full_name": "example/product"}], False)
        ):
            if control:
                assert InboxOnboardingReconciler(self.team.id).run() is (enabled is False)
            else:
                response = self.client.post(f"{self.url}complete/", self.draft, format="json")
                assert response.status_code == (400 if enabled is False else 200), response.json()
        config.refresh_from_db()
        assert bool((config.onboarding or {}).get("completed_at")) is (enabled is not False)

    @parameterized.expand(
        [
            (False, "scout", 403),
            (True, "scout", 200),
            (False, "source", 403),
            (True, "source", 200),
            (False, "none", 200),
        ]
    )
    def test_child_completion_checks_parent_scout_access(
        self, parent_access: bool, selection: str, expected_status: int
    ) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
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

    @parameterized.expand([("",), ("complete/",), ("expose/",), ("reconcile/",)])
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

    @parameterized.expand([("expose",), ("reconcile",)])
    def test_child_scoped_credential_cannot_start_parent_reconciliation(self, action: str) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="onboarding",
            user=self.user,
            secure_value=hash_key_value(raw),
            scopes=["task:write"],
            scoped_teams=[child.id],
        )
        self.client.logout()
        response = self.client.post(
            f"/api/projects/{child.id}/signals/onboarding/{action}/",
            {"variant": "control"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {raw}",
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

    @parameterized.expand([("recovered",), ("expired",), ("manual",), ("completed",)])
    def test_background_polling_survives_outage_and_stops(self, terminal_state: str) -> None:
        config = SignalTeamConfig.objects.get(team=self.team)
        config.onboarding = {"variant": "control", "exposed_at": timezone.now().isoformat()}
        config.save()
        Integration.objects.create(team=self.team, kind="github")
        with (
            patch.object(
                GitHubIntegration, "list_repositories", side_effect=GitHubRateLimitError("limited")
            ) as listing,
            patch.object(reconcile_inbox_onboarding, "apply_async") as schedule,
        ):
            failed_checks = 0
            for _ in range(7):
                schedule.reset_mock()
                reconcile_inbox_onboarding.run(self.team.id, failed_checks=failed_checks)
                schedule.assert_called_once()
                assert 60 <= schedule.call_args.kwargs["countdown"] <= 900
                failed_checks = schedule.call_args.kwargs["kwargs"]["failed_checks"]
            config.refresh_from_db()
            assert not config.onboarding.get("completed_at")
            if terminal_state == "expired":
                config.onboarding["exposed_at"] = (timezone.now() - timedelta(days=8)).isoformat()
            elif terminal_state == "manual":
                config.onboarding["draft"] = self.draft
            elif terminal_state == "completed":
                config.onboarding["completed_at"] = timezone.now().isoformat()
            config.save()
            schedule.reset_mock()
            listing.reset_mock()
            listing.side_effect = None
            listing.return_value = ([{"full_name": "example/product"}], False)
            reconcile_inbox_onboarding.run(self.team.id, failed_checks=failed_checks)
            schedule.assert_not_called()
            if terminal_state == "recovered":
                config.refresh_from_db()
                assert config.onboarding["completed_at"]
            else:
                listing.assert_not_called()

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
            "variant": "test-github",
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

    def test_background_polling_honors_github_retry_hint(self) -> None:
        config = SignalTeamConfig.objects.get(team=self.team)
        config.onboarding = {"variant": "control", "exposed_at": timezone.now().isoformat()}
        config.save()
        Integration.objects.create(team=self.team, kind="github")
        with (
            patch.object(
                GitHubIntegration, "list_repositories", side_effect=GitHubRateLimitError("limited", retry_after=3600)
            ),
            patch.object(reconcile_inbox_onboarding, "apply_async") as schedule,
        ):
            reconcile_inbox_onboarding.run(self.team.id, failed_checks=6)
        assert schedule.call_args.kwargs["countdown"] == 3600


class TestInboxOnboardingActivation(BaseTest):
    @parameterized.expand([("scout", 0), ("scout", 5), ("recommendations", 0), ("recommendations", 5)])
    def test_dispatch_retries_use_one_workflow_and_preserve_completed_jobs(self, job: str, retry_count: int) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        config = SignalTeamConfig.objects.create(
            team=self.team,
            onboarding={
                "variant": "test-github",
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
            patch("products.signals.backend.onboarding_activation.ph_scoped_capture") as capture,
            patch("products.signals.backend.onboarding_analytics.posthoganalytics.feature_enabled", return_value=True),
            self.captureOnCommitCallbacks(execute=True),
            patch("products.signals.backend.temporal.agentic.scout_suggestions.stamp_requested"),
            patch(
                "posthoganalytics.get_feature_flag_payload",
                return_value={"enabled": True, "guaranteed_team_ids": [self.team.id]},
            ),
        ):
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
                "variant": "test-github",
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
