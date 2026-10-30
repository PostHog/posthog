from contextlib import AbstractContextManager
from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models import OrganizationMembership, Team, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.signals.backend.models import SignalScoutConfig, SignalSourceConfig
from products.signals.backend.trial.billing import TrialBillingStatus, TrialContinuation
from products.signals.backend.trial.models import SignalTrialGrant
from products.signals.backend.trial.policy import TrialPolicy
from products.skills.backend.models.skills import LLMSkill


class TestTrialAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self.url = f"/api/projects/{self.team.pk}/signals/trial/"
        self.flag = patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True)
        self.flag_mock = self.flag.start()
        self.addCleanup(self.flag.stop)

    @parameterized.expand(
        [
            ("trial", "member", 3, 403),
            ("source", "member", 3, 403),
            ("trial", "owner", 3, 200),
            ("source", "admin", 3, 201),
            ("trial", "member", 0, 200),
            ("source", "member", None, 201),
        ]
    )
    def test_activation_preserves_locked_scout_permissions(
        self, path: str, role: str, locked_index: int | None, expected_status: int
    ) -> None:
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN if role == "admin" else OrganizationMembership.Level.MEMBER
        )
        owner = (
            self.user
            if role == "owner"
            else User.objects.create_and_join(self.organization, "scout-owner@example.com", None)
        )
        scouts = []
        for index in range(4):
            name = f"signals-scout-permission-{index}"
            LLMSkill.objects.create(
                team=self.team, name=name, description="Example scout", body="# Scout", created_by=owner
            )
            scouts.append(
                SignalScoutConfig.objects.create(
                    team=self.team, skill_name=name, created_by=owner, lifecycle_locked=index == locked_index
                )
            )
        SignalScoutConfig.objects.filter(id__in=[scout.id for scout in scouts[:3]]).update(
            created_at=timezone.now() - timedelta(days=1)
        )
        if role == "member" and locked_index is not None:
            direct = self.client.patch(
                f"/api/projects/{self.team.pk}/signals/scout/configs/{scouts[locked_index].id}/",
                {"enabled": False},
                format="json",
            )
            assert direct.status_code == 403, direct.content

        with (
            patch(
                "products.signals.backend.trial.billing.TrialBilling.status",
                return_value=TrialBillingStatus(ready=True, continuation=TrialContinuation.PAYMENT),
            ),
            patch("products.signals.backend.views.SignalSourceConfigViewSet._trigger_error_tracking_backfill"),
        ):
            response = self.client.post(
                self.url if path == "trial" else f"/api/projects/{self.team.pk}/signals/source_configs/",
                {}
                if path == "trial"
                else {"source_product": "error_tracking", "source_type": "issue_created", "enabled": True},
                format="json",
            )
        assert response.status_code == expected_status, response.content
        allowed = expected_status != 403
        assert SignalTrialGrant.objects.for_team(self.team.id).exists() is allowed
        for scout in scouts:
            scout.refresh_from_db()
        assert [scout.enabled for scout in scouts] == ([True, True, True, False] if allowed else [True] * 4)
        if path == "source":
            assert SignalSourceConfig.objects.filter(team=self.team, enabled=True).exists() is allowed

    @parameterized.expand(
        [(path, allowed) for path in ("trial", "source", "source_update") for allowed in (False, True)]
    )
    def test_child_activation_requires_credential_access_to_parent(self, path: str, allowed: bool) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        scouts = [
            SignalScoutConfig.objects.create(team=self.team, skill_name=f"signals-scout-access-{i}") for i in range(4)
        ]
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Trial project access",
            user=self.user,
            secure_value=hash_key_value(raw),
            scopes=["project:write", "task:write"],
            scoped_teams=[child.id, self.team.id] if allowed else [child.id],
        )
        self.client.logout()
        data = {"source_product": "error_tracking", "source_type": "issue_created", "enabled": True}
        url = f"/api/projects/{child.id}/signals/{'trial' if path == 'trial' else 'source_configs'}/"
        if path == "source_update":
            source = SignalSourceConfig.objects.create(team=child, **{**data, "enabled": False})
            url += f"{source.id}/"
        with (
            patch(
                "products.signals.backend.trial.billing.TrialBilling.status",
                return_value=TrialBillingStatus(ready=True, continuation=TrialContinuation.PAYMENT),
            ),
            patch("products.signals.backend.views.SignalSourceConfigViewSet._trigger_error_tracking_backfill"),
        ):
            response = (self.client.patch if path == "source_update" else self.client.post)(
                url, {} if path == "trial" else data, format="json", HTTP_AUTHORIZATION=f"Bearer {raw}"
            )
        assert response.status_code == ((201 if path == "source" else 200) if allowed else 403), response.content
        assert SignalTrialGrant.objects.for_team(self.team.id).exists() is allowed
        for scout in scouts:
            scout.refresh_from_db()
        assert sum(scout.enabled for scout in scouts) == (3 if allowed else 4)

    @parameterized.expand([(False,), (True,)])
    def test_source_activation_enrolls_once_before_backfill(self, existing: bool) -> None:
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.MEMBER
        )
        url = f"/api/projects/{self.team.pk}/signals/source_configs/"
        data = {"source_product": "error_tracking", "source_type": "issue_created", "enabled": True}
        source = SignalSourceConfig.objects.create(team=self.team, **{**data, "enabled": False}) if existing else None
        if source:
            url += f"{source.pk}/"

        def assert_enrolled() -> None:
            assert SignalTrialGrant.objects.for_team(self.team.pk).exists()

        with (
            patch(
                "products.signals.backend.trial.billing.TrialBilling.status",
                return_value=TrialBillingStatus(ready=True, continuation=TrialContinuation.PAYMENT),
            ),
            patch(
                "products.signals.backend.views.SignalSourceConfigViewSet._trigger_error_tracking_backfill",
                side_effect=assert_enrolled,
            ),
        ):
            response = (self.client.patch if existing else self.client.post)(url, data, format="json")
        assert response.status_code == (200 if existing else 201), response.content
        grant = SignalTrialGrant.objects.for_team(self.team.pk).get()
        assert grant.claimed_by_id == self.user.pk
        SignalTrialGrant.objects.for_team(self.team.pk).update(settled_microusd=123)
        with patch("products.signals.backend.trial.billing.TrialBilling.status", side_effect=TimeoutError()):
            retry = self.client.patch(
                f"/api/projects/{self.team.pk}/signals/source_configs/{response.json()['id']}/",
                {"enabled": True},
                format="json",
            )
        assert retry.status_code == 200, retry.content
        grant.refresh_from_db()
        assert grant.settled_microusd == 123
        assert SignalTrialGrant.objects.for_team(self.team.pk).count() == 1

    @parameterized.expand([("billing", 402), ("flag_unavailable", 402)])
    def test_failed_enrollment_leaves_source_disabled(self, failure: str, expected_status: int) -> None:
        source = SignalSourceConfig.objects.create(
            team=self.team, source_product="github", source_type="issue", enabled=False
        )
        if failure == "flag_unavailable":
            assert TrialPolicy(self.team).enabled()
            self.flag_mock.return_value = None
        with patch(
            "products.signals.backend.trial.billing.TrialBilling.status",
            return_value=TrialBillingStatus(ready=failure != "billing", continuation=TrialContinuation.PAYMENT),
        ):
            response = self.client.patch(
                f"/api/projects/{self.team.pk}/signals/source_configs/{source.pk}/", {"enabled": True}, format="json"
            )
        assert response.status_code == expected_status, response.content
        source.refresh_from_db()
        assert not source.enabled
        assert not SignalTrialGrant.objects.for_team(self.team.pk).exists()

    @parameterized.expand([(False, True), (True, False)])
    def test_flag_off_and_disabled_sources_do_not_enroll(self, flag: bool, enabled: bool) -> None:
        self.flag_mock.return_value = flag
        with patch("products.signals.backend.trial.billing.TrialBilling.status") as billing:
            response = self.client.post(
                f"/api/projects/{self.team.pk}/signals/source_configs/",
                {"source_product": "github", "source_type": "issue", "enabled": enabled},
                format="json",
            )
        assert response.status_code == 201, response.content
        assert response.json()["enabled"] is enabled
        assert not SignalTrialGrant.objects.for_team(self.team.pk).exists()
        billing.assert_not_called()

    @parameterized.expand([(TrialContinuation.PAID, 201), (TrialContinuation.PAYMENT, 402)])
    def test_organization_trial_limit_preserves_paid_activation(
        self, continuation: TrialContinuation, expected_status: int
    ) -> None:
        for index in range(3):
            team = Team.objects.create(organization=self.organization, name=f"Trial project {index}")
            TrialPolicy(team).claim(user_id=self.user.pk)
        with patch(
            "products.signals.backend.trial.billing.TrialBilling.status",
            return_value=TrialBillingStatus(ready=True, continuation=continuation),
        ):
            response = self.client.post(
                f"/api/projects/{self.team.pk}/signals/source_configs/",
                {"source_product": "github", "source_type": "issue", "enabled": True},
                format="json",
            )
        assert response.status_code == expected_status, response.content
        assert not SignalTrialGrant.objects.for_team(self.team.pk).exists()
        assert SignalSourceConfig.objects.filter(team=self.team, enabled=True).exists() is (expected_status == 201)

    @parameterized.expand([("config_create",), ("config_update",), ("custom",)])
    def test_scout_activation_enrolls(self, path: str) -> None:
        name = "signals-scout-enrollment"
        url = f"/api/projects/{self.team.pk}/signals/scout/"
        data: dict[str, object] = {"name": name, "description": "Find errors", "body": "Investigate errors."}
        if path != "custom":
            LLMSkill.objects.create(team=self.team, name=name, body="Investigate errors.", created_by=self.user)
            url += "configs/"
            data = {"skill_name": name, "enabled": True}
        if path == "config_update":
            config = SignalScoutConfig.objects.create(team=self.team, skill_name=name, enabled=False)
            url += f"{config.pk}/"
            data = {"enabled": True}
        with patch(
            "products.signals.backend.trial.billing.TrialBilling.status",
            return_value=TrialBillingStatus(ready=True, continuation=TrialContinuation.PAYMENT),
        ):
            response = (self.client.patch if path == "config_update" else self.client.post)(url, data, format="json")
        assert response.status_code in (200, 201), response.content
        assert SignalTrialGrant.objects.for_team(self.team.pk).exists()
        assert SignalScoutConfig.objects.for_team(self.team.pk).get(skill_name=name).enabled

    def test_rejected_scout_activation_rolls_back_grant_and_paused_scouts(self) -> None:
        configs = [
            SignalScoutConfig.objects.create(team=self.team, skill_name=f"signals-scout-existing-{i}") for i in range(4)
        ]
        capture = Mock()
        with (
            patch(
                "products.signals.backend.trial.billing.TrialBilling.status",
                return_value=TrialBillingStatus(ready=True, continuation=TrialContinuation.PAYMENT),
            ),
            patch("products.signals.backend.trial.service.report_user_action", new=capture),
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.post(
                f"/api/projects/{self.team.pk}/signals/scout/configs/",
                {"skill_name": "signals-scout-missing", "enabled": True},
                format="json",
            )
        assert response.status_code == 400, response.content
        assert [call.kwargs["properties"]["outcome"] for call in capture.call_args_list] == ["attempted", "failed"]
        assert not SignalTrialGrant.objects.for_team(self.team.pk).exists()
        assert (
            SignalScoutConfig.objects.for_team(self.team.pk)
            .filter(id__in=[c.id for c in configs], enabled=True)
            .count()
            == 4
        )

    @parameterized.expand(
        [(None, True), ("wizard", True), ("onboarding", False), ("roster", False), ("desktop", False)]
    )
    def test_sync_enrolls_only_activation_surfaces(self, surface: str | None, enrolled: bool) -> None:
        url = f"/api/projects/{self.team.pk}/signals/scout/configs/sync/"
        if surface:
            url += f"?surface={surface}"

        def materialize(team: Team, *, surface: str | None, activation: AbstractContextManager[None]) -> set[str]:
            with activation:
                assert SignalTrialGrant.objects.for_team(self.team.pk).exists() is enrolled
            return set()

        with (
            patch(
                "products.signals.backend.trial.billing.TrialBilling.status",
                return_value=TrialBillingStatus(ready=True, continuation=TrialContinuation.PAYMENT),
            ),
            patch("products.signals.backend.scout_harness.views.materialize_scout_fleet", side_effect=materialize),
        ):
            response = self.client.post(url, {}, format="json")
        assert response.status_code == 200, response.content
        assert SignalTrialGrant.objects.for_team(self.team.pk).exists() is enrolled

    @parameterized.expand(
        [(10_000_000, 5, 20_000_000, 10), (20_000_000, 10, 10_000_000, 5), (20_000_000, 10, None, None)]
    )
    def test_plan_limits_are_snapshotted_at_activation(
        self, allowance: int, reports: int, next_allowance: int | None, next_reports: int | None
    ) -> None:
        customer = {
            "usage_summary": {"signals_spend_credits": {"billing_start_date": "2026-01-01"}},
            "has_active_subscription": False,
            "available_product_features": [
                {"key": "self_driving_trial_allowance_microusd", "limit": allowance},
                {"key": "self_driving_trial_reports", "limit": reports},
            ],
            "products": [
                {
                    "type": "inbox_usage",
                    "usage_key": "signals_spend_credits",
                    "subscribed": None,
                    "free_allocation": 0,
                    "usage_limit": 0,
                }
            ],
        }
        with (
            patch("products.signals.backend.trial.billing.get_cached_instance_license", return_value=Mock()),
            patch(
                "products.signals.backend.trial.billing.BillingManager.get_billing",
                return_value=customer,
            ),
        ):
            offer = self.client.get(self.url).json()
            assert offer["allowance_microusd"] == allowance
            assert offer["report_limit"] == reports
            started = self.client.post(
                self.url, {"allowance_microusd": 100_000_000, "report_limit": 100}, format="json"
            )
            assert started.status_code == 200, started.content
            assert started.json()["allowance_microusd"] == allowance
            assert started.json()["report_limit"] == reports
            grant_id = started.json()["grant_id"]
            SignalTrialGrant.objects.for_team(self.team.pk).update(settled_microusd=3_000_000)
            customer["available_product_features"] = [
                {"key": "self_driving_trial_allowance_microusd", "limit": next_allowance},
                {"key": "self_driving_trial_reports", "limit": next_reports},
            ]
            for response in [self.client.get(self.url), self.client.post(self.url, {}, format="json")]:
                assert response.status_code == 200, response.content
                status = response.json()
                assert status["grant_id"] == grant_id
                assert status["allowance_microusd"] == allowance
                assert status["report_limit"] == reports
                assert status["used_microusd"] == 3_000_000
            assert SignalTrialGrant.objects.unscoped().filter(organization_id=self.organization.id).count() == 1

    @parameterized.expand(
        [
            (continuation, level)
            for continuation in (TrialContinuation.PAYMENT, TrialContinuation.LIMIT, TrialContinuation.PAID)
            for level in (OrganizationMembership.Level.MEMBER, OrganizationMembership.Level.ADMIN)
        ]
    )
    def test_all_cohorts_can_explicitly_claim_once(self, continuation: TrialContinuation, level: int) -> None:
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(level=level)
        with patch(
            "products.signals.backend.trial.billing.TrialBilling.status",
            return_value=TrialBillingStatus(ready=True, continuation=continuation),
        ):
            status = self.client.get(self.url)
            assert status.status_code == 200
            assert status.json()["eligible"]
            assert status.json()["can_activate"]
            assert status.json()["legacy_pr_restricted"]
            assert not SignalTrialGrant.objects.for_team(self.team.pk).exists()
            first = self.client.post(self.url, {}, format="json")
            second = self.client.post(self.url, {}, format="json")
        assert first.status_code == 200, first.content
        assert first.json()["grant_id"] == second.json()["grant_id"]
        assert first.json()["paid_continuation"] == continuation
        assert first.json()["legacy_pr_restricted"] is False
        assert SignalTrialGrant.objects.unscoped().filter(organization_id=self.organization.id).count() == 1

    def test_member_activation_with_unready_billing_does_not_consume_grant(self) -> None:
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save(update_fields=["level"])
        with patch(
            "products.signals.backend.trial.billing.TrialBilling.status",
            return_value=TrialBillingStatus(
                ready=False,
                continuation=TrialContinuation.PAYMENT,
            ),
        ):
            assert self.client.post(self.url, {}, format="json").status_code == 400
        assert not SignalTrialGrant.objects.for_team(self.team.pk).exists()

    @parameterized.expand([(True,), (False,)])
    def test_enrollment_events_distinguish_committed_activation_and_refusal(self, ready: bool) -> None:
        capture = Mock()
        with (
            patch("products.signals.backend.trial.service.report_user_action", new=capture),
            patch(
                "products.signals.backend.trial.billing.TrialBilling.status",
                return_value=TrialBillingStatus(ready=ready, continuation=TrialContinuation.PAYMENT),
            ),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(self.url, {}, format="json")
                assert response.status_code == (200 if ready else 400), response.content
                assert [call.kwargs["properties"]["outcome"] for call in capture.call_args_list] == (
                    ["attempted"] if ready else ["attempted", "refused"]
                )
            outcomes = [call.kwargs["properties"] for call in capture.call_args_list]
            assert outcomes[-1]["outcome"] == ("activated" if ready else "refused")
            assert outcomes[-1]["reason"] == (None if ready else "billing_not_ready")
            assert outcomes[-1]["grant_id"] == (response.json()["grant_id"] if ready else None)

    def test_failed_billing_read_does_not_consume_grant(self) -> None:
        with patch("products.signals.backend.trial.billing.TrialBilling.status", side_effect=TimeoutError()):
            assert self.client.post(self.url, {}, format="json").status_code == 400
        assert not SignalTrialGrant.objects.for_team(self.team.pk).exists()
        with patch(
            "products.signals.backend.trial.billing.TrialBilling.status",
            return_value=TrialBillingStatus(ready=True, continuation=TrialContinuation.PAYMENT),
        ):
            response = self.client.post(self.url, {}, format="json")
        assert response.status_code == 200, response.content
        grant = SignalTrialGrant.objects.for_team(self.team.pk).get()
        assert response.json()["grant_id"] == str(grant.id)
        assert response.json()["grant_status"] == "active"

    def test_flag_off_hides_offer_and_prevents_activation_for_claimed_projects(self) -> None:
        with patch(
            "products.signals.backend.trial.billing.TrialBilling.status",
            return_value=TrialBillingStatus(ready=True, continuation=TrialContinuation.PAYMENT),
        ):
            response = self.client.post(self.url, {}, format="json")
            assert response.status_code == 200
            grant_id = response.json()["grant_id"]
            self.flag_mock.assert_called_with(
                "self-driving-ubp",
                str(self.organization.id),
                groups={"organization": str(self.organization.id)},
                group_properties={"organization": {"id": str(self.organization.id)}},
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
            self.flag_mock.return_value = False
            status = self.client.get(self.url).json()
            assert not status["enabled"]
            assert status["grant_status"] == "active"
            assert status["grant_id"] == grant_id
            assert not status["eligible"]
            other = Team.objects.create(organization=self.organization, name="Other project")
            other_url = f"/api/projects/{other.id}/signals/trial/"
            assert not self.client.get(other_url).json()["enabled"]
            assert self.client.post(other_url, {}, format="json").status_code == 400
        with patch("products.signals.backend.trial.billing.TrialBilling.status", side_effect=TimeoutError()):
            retry = self.client.post(self.url, {}, format="json")
        assert retry.status_code == 400
        assert SignalTrialGrant.objects.unscoped().filter(organization_id=self.organization.id).count() == 1
