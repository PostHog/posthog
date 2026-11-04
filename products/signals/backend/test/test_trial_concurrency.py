from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.db import OperationalError, close_old_connections, connection, transaction

from rest_framework.test import APIClient

from posthog.models import OrganizationMembership, Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import SignalReport, SignalScoutConfig
from products.signals.backend.report_generation.research import ReportLayer
from products.signals.backend.scout_harness.skill_loader import REPORT_CHANNEL_TOOLS
from products.signals.backend.stack_plan import create_layer_reports
from products.signals.backend.trial.billing import TrialBillingStatus, TrialContinuation
from products.signals.backend.trial.limits import STANDARD_TRIAL_LIMITS, TrialLimits
from products.signals.backend.trial.models import SignalTrialGrant, SignalTrialReportReservation
from products.signals.backend.trial.policy import TrialPolicy, TrialRefused
from products.signals.backend.trial.service import TrialService
from products.skills.backend.models.skills import LLMSkill


class TestTrialConcurrency(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_custom_activation_resolves_remote_inputs_before_skill_and_grant_locks(self) -> None:
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        name = "signals-scout-activation-order"
        skill = LLMSkill.objects.create(
            team=self.team,
            name=name,
            description="Inspect test signals",
            body="Investigate errors.",
            category="scout",
            allowed_tools=sorted(REPORT_CHANNEL_TOOLS),
            created_by=self.user,
        )
        SignalScoutConfig.objects.for_team(self.team.id).create(team=self.team, skill_name=name, enabled=False)
        original = TrialPolicy.claim

        def can_lock_skill() -> bool:
            close_old_connections()
            try:
                with transaction.atomic():
                    LLMSkill.objects.select_for_update(nowait=True).get(team=self.team, id=skill.id)
                return True
            except OperationalError as error:
                assert getattr(error.__cause__, "sqlstate", None) == "55P03"
                return False
            finally:
                close_old_connections()

        def claim(
            policy: TrialPolicy,
            *,
            user_id: int,
            limits: TrialLimits = STANDARD_TRIAL_LIMITS,
            api_scopes: list[str] | None = None,
        ) -> SignalTrialGrant:
            with ThreadPoolExecutor(max_workers=1) as pool:
                assert not pool.submit(can_lock_skill).result(timeout=10)
            return original(policy, user_id=user_id, limits=limits, api_scopes=api_scopes)

        def billing() -> TrialBillingStatus:
            assert not connection.in_atomic_block
            return TrialBillingStatus(ready=True, continuation=TrialContinuation.PAYMENT)

        def flag_payload() -> None:
            assert not connection.in_atomic_block
            return None

        client = APIClient()
        client.force_login(self.user)
        with (
            patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True),
            patch("products.signals.backend.trial.billing.TrialBilling.status", side_effect=billing),
            patch("products.signals.backend.scout_harness.team_limits._read_flag_payload", side_effect=flag_payload),
            patch.object(TrialPolicy, "claim", claim),
        ):
            response = client.post(
                f"/api/projects/{self.team.id}/signals/scout/",
                {"name": name, "description": skill.description, "body": skill.body, "config": {"enabled": True}},
                format="json",
            )
        assert response.status_code == 200, response.content
        assert SignalScoutConfig.objects.for_team(self.team.id).get(skill_name=name).enabled
        assert SignalTrialGrant.objects.for_team(self.team.id).exists()

    def test_concurrent_plans_reserve_all_layers_or_publish_only_parent(self) -> None:
        with patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True):
            policy = TrialPolicy(self.team)
            policy.claim(user_id=self.user.pk)
            parents = [
                SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS) for _ in range(2)
            ]
            for parent in parents:
                policy.admit(
                    report_id=parent.id,
                    paid_authorized=False,
                )
                parent.status = SignalReport.Status.READY
                parent.save(update_fields=["status"])
            barrier = Barrier(2)

            def publish_layers(parent: SignalReport) -> int:
                close_old_connections()
                try:
                    barrier.wait(timeout=10)
                    return len(
                        create_layer_reports(
                            parent=parent,
                            layers=[
                                ReportLayer(title="First", scope="First step"),
                                ReportLayer(title="Second", scope="Second step", depends_on=0),
                            ],
                            attribution=ArtefactAttribution.system(),
                        )
                    )
                finally:
                    close_old_connections()

            with ThreadPoolExecutor(max_workers=2) as pool:
                assert sorted(pool.map(publish_layers, parents)) == [0, 2]
            assert SignalTrialReportReservation.objects.for_team(self.team.id).filter(status="consumed").count() == 4
            assert not SignalTrialReportReservation.objects.for_team(self.team.id).filter(status="reserved").exists()

    def test_final_organization_slot_and_report_slot_are_atomic(self) -> None:
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        with (
            patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True),
            patch(
                "products.signals.backend.trial.billing.TrialBilling.status",
                return_value=TrialBillingStatus(ready=True, continuation=TrialContinuation.PAYMENT),
            ),
        ):
            TrialPolicy(self.team).claim(user_id=self.user.pk)
            second = Team.objects.create(organization=self.organization, name="Second")
            TrialPolicy(second).claim(user_id=self.user.pk)
            contenders = [Team.objects.create(organization=self.organization, name=f"Project {i}") for i in range(2)]
            barrier = Barrier(2)

            def claim(team: Team) -> bool:
                close_old_connections()
                try:
                    barrier.wait(timeout=10)
                    with TrialService(team).enroll_on_activation(user=self.user, enabled=True, api_scopes=None):
                        pass
                    return True
                except TrialRefused:
                    return False
                finally:
                    close_old_connections()

            with ThreadPoolExecutor(max_workers=2) as pool:
                assert sorted(pool.map(claim, contenders)) == [False, True]
            assert TrialPolicy(self.team).organization_grants_claimed() == 3
            policy = TrialPolicy(self.team)

            def publish() -> bool:
                report = uuid4()
                try:
                    policy.admit(
                        report_id=report,
                        paid_authorized=False,
                    )
                    with policy.publish_report(report, delivered=True):
                        pass
                    return True
                except TrialRefused:
                    return False

            for _ in range(4):
                assert publish()
            barrier = Barrier(2)

            def race_publish(_: int) -> bool:
                close_old_connections()
                try:
                    barrier.wait(timeout=10)
                    return publish()
                finally:
                    close_old_connections()

            with ThreadPoolExecutor(max_workers=2) as pool:
                assert sorted(pool.map(race_publish, range(2))) == [False, True]
            assert SignalTrialReportReservation.objects.for_team(self.team.id).filter(status="consumed").count() == 5
