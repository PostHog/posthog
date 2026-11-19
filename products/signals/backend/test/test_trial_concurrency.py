from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from threading import Barrier, Event
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.db import OperationalError, close_old_connections, connection, transaction

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models import OrganizationMembership, Team

from products.signals.backend import spend as spend_module
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.facade.trial import TaskTrialAdmission
from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalSpend
from products.signals.backend.rated_usage_models import SignalRatedUsage
from products.signals.backend.report_generation.research import ReportLayer
from products.signals.backend.scout_harness.skill_loader import REPORT_CHANNEL_TOOLS
from products.signals.backend.spend import record_llm_spend
from products.signals.backend.stack_plan import create_layer_reports
from products.signals.backend.test.test_billing import _at
from products.signals.backend.trial.billing import TrialBillingStatus, TrialContinuation
from products.signals.backend.trial.limits import STANDARD_TRIAL_LIMITS, TrialLimits
from products.signals.backend.trial.models import SignalTrialGrant
from products.signals.backend.trial.policy import TrialPolicy, TrialRefused
from products.signals.backend.trial.rated_usage import snapshot_rated_usage, trial_pool_id
from products.signals.backend.trial.service import TrialService
from products.signals.backend.usage import trial_usage
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.models import Task


class TestTrialConcurrency(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    @parameterized.expand([(10, 1), (11, 2)])
    def test_concurrent_child_usage_does_not_overdraw_the_shared_trial_pool(
        self, second_day: int, expected_deliveries: int
    ) -> None:
        with time_machine.travel(_at(9), tick=False):
            grant = SignalTrialGrant.objects.for_team(self.team.id).create(
                team_id=self.team.id, organization_id=self.organization.id, claimed_by_id=self.user.id
            )
        child = Team.objects.create(organization=self.organization, project=self.team.project, parent_team=self.team)
        for team, day in ((self.team, 10), (child, second_day)):
            SignalSpend.objects.for_team(team.id).create(
                team=team,
                signal_id=uuid4(),
                kind=SignalSpend.Kind.AD_HOC,
                spend=Decimal("600"),
                finalized_at=_at(day),
                billing_exempt=True,
                trial_grant=grant,
            )
        barrier = Barrier(2)

        def report(day: int) -> None:
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                snapshot_rated_usage(self.organization.id, date(2026, 6, day))
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(report, 10), pool.submit(report, second_day)
            first.result(timeout=30)
            second.result(timeout=30)
        deliveries = list(SignalRatedUsage.objects.unscoped().filter(organization_id=self.organization.id))
        assert len(deliveries) == expected_deliveries
        assert {delivery.team_id for delivery in deliveries} == {self.team.id}
        assert sum(delivery.cents for delivery in deliveries) == 1200
        shares = [share for delivery in deliveries for share in delivery.grants]
        assert sum(share["cents"] for share in shares if share["grant_id"] == trial_pool_id(grant)) == 1000
        assert sum(share["cents"] for share in shares if share["grant_id"] != trial_pool_id(grant)) == 200
        grant.refresh_from_db()
        assert grant.billing_pool_allocated_cents == 1000

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

    def test_concurrent_accepted_plans_publish_all_layers_after_the_report_limit(self) -> None:
        with patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True):
            policy = TrialPolicy(self.team)
            grant = policy.claim(user_id=self.user.pk)
            parents = [
                SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS) for _ in range(2)
            ]
            for parent in parents:
                policy.admit(
                    report_id=parent.id,
                    paid_authorized=False,
                )
                parent.refresh_from_db()
                parent.save(
                    update_fields=parent.transition_to(SignalReport.Status.READY, title="Plan", summary="Summary")
                )
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
                assert sorted(pool.map(publish_layers, parents)) == [2, 2]
            assert SignalReport.objects.filter(team=self.team, status=SignalReport.Status.READY).count() == 6
            assert trial_usage(grant).reports == 6
            assert trial_usage(grant).running_reports == 0

    def test_final_organization_claim_and_report_admission_are_atomic(self) -> None:
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
            assert TrialPolicy(self.team).organization_grants_claimed() == 1
            winning_team = next(team for team in contenders if TrialPolicy(team).grant() is not None)
            policy = TrialPolicy(winning_team)

            def publish() -> bool:
                report = SignalReport.objects.create(team=winning_team)
                try:
                    policy.admit(
                        report_id=report.id,
                        paid_authorized=False,
                    )
                    report.refresh_from_db()
                    report.status = SignalReport.Status.IN_PROGRESS
                    report.save(update_fields=["status"])
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
            grant = policy.grant()
            assert grant is not None
            assert trial_usage(grant).running_reports == 5

    def test_report_finalization_and_late_settlement_share_a_grant_without_deadlocking(self) -> None:
        with patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True):
            grant = TrialPolicy(self.team).claim(user_id=self.user.pk)
        first_id, pending_id = uuid4(), uuid4()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.IN_PROGRESS,
            triggering_signal_id=first_id,
            pending_triggering_signal_id=pending_id,
        )
        spend_module.record_llm_spend(
            team_id=self.team.id,
            signal_id=str(first_id),
            stage="research",
            token_cost_microusd=100,
            trial_grant_id=str(grant.id),
        )
        spend_module.record_llm_spend(
            team_id=self.team.id,
            signal_id=str(pending_id),
            stage="research",
            token_cost_microusd=None,
            source_id="late",
            trial_grant_id=str(grant.id),
            strict=True,
        )
        first_locked, pending_locked, finalizing_pending = Event(), Event(), Event()
        lock_spend = spend_module._locked_ad_hoc_spend

        def coordinated_lock(*, team_id: int, signal_id: str, trial_grant_id: str | None = None) -> SignalSpend:
            if signal_id == str(pending_id):
                finalizing_pending.set()
            receipt = lock_spend(team_id=team_id, signal_id=signal_id, trial_grant_id=trial_grant_id)
            if signal_id == str(first_id):
                first_locked.set()
                assert pending_locked.wait(timeout=10)
            return receipt

        def finalize() -> None:
            close_old_connections()
            try:
                spend_module.finish_report_spend(
                    team_id=self.team.id, report_id=str(report.id), signal_id=str(first_id)
                )
            finally:
                close_old_connections()

        def settle() -> None:
            close_old_connections()
            try:
                assert first_locked.wait(timeout=10)
                with transaction.atomic():
                    spend_module.lock_signal_spend(team_id=self.team.id, signal_id=str(pending_id))
                    SignalSpend.objects.for_team(self.team.id).select_for_update().get(signal_id=pending_id)
                    pending_locked.set()
                    assert finalizing_pending.wait(timeout=10)
                    spend_module.record_llm_spend(
                        "late-request",
                        team_id=self.team.id,
                        signal_id=str(pending_id),
                        stage="research",
                        source_id="late",
                        token_cost_microusd=200,
                    )
            finally:
                close_old_connections()

        with patch.object(spend_module, "_locked_ad_hoc_spend", side_effect=coordinated_lock):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(finalize), pool.submit(settle)]
                for future in futures:
                    future.result(timeout=15)
        assert trial_usage(grant).settled_microusd == 300
        assert SignalSpend.objects.for_team(self.team.id).filter(finalized_at__isnull=False).count() == 2
        report.refresh_from_db()
        assert report.pending_triggering_signal_id is None

    def test_report_lock_precedes_trial_grant_lock_during_admission(self) -> None:
        with patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True):
            TrialPolicy(self.team).claim(user_id=self.user.pk)
            report = SignalReport.objects.create(team=self.team, triggering_signal_id=uuid4())
            task = Task.objects.create(
                team=self.team,
                title="Report admission",
                origin_product="signal_report",
                signal_report=report,
                internal=True,
            )
            original = TrialPolicy.locked_grant

            def can_lock_report() -> bool:
                close_old_connections()
                try:
                    with transaction.atomic():
                        SignalReport.objects.select_for_update(nowait=True).get(team_id=self.team.id, id=report.id)
                    return True
                except OperationalError as error:
                    assert getattr(error.__cause__, "sqlstate", None) == "55P03"
                    return False
                finally:
                    close_old_connections()

            @contextmanager
            def lock_grant(policy: TrialPolicy, grant_id: UUID) -> Iterator[SignalTrialGrant]:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    assert not pool.submit(can_lock_report).result(timeout=10)
                with original(policy, grant_id) as grant:
                    yield grant

            with patch.object(TrialPolicy, "locked_grant", lock_grant):
                task.create_run(extra_state={"ai_stage": "implementation"})

    def test_admission_and_cost_settlement_do_not_invert_locks(self) -> None:
        with patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True):
            grant = TrialPolicy(self.team).claim(user_id=self.user.pk)
            signal_id = str(uuid4())
            report = SignalReport.objects.create(team=self.team, triggering_signal_id=signal_id)
            task = Task.objects.create(
                team=self.team,
                title="Concurrent run",
                origin_product="signal_report",
                signal_report_id=report.id,
                internal=True,
            )
            record_llm_spend(
                "initial",
                team_id=self.team.id,
                signal_id=signal_id,
                stage="research",
                token_cost_microusd=1,
                trial_grant_id=str(grant.id),
            )
            spend_locked, grant_locked = Event(), Event()
            original_bind = TaskTrialAdmission.bind

            def bind(
                admission: TaskTrialAdmission,
                *,
                origin: str,
                stage: str,
                report_id: UUID | None,
                task_runtime: str,
                model_access: str,
            ) -> dict[str, str | int]:
                result = original_bind(
                    admission,
                    origin=origin,
                    stage=stage,
                    report_id=report_id,
                    task_runtime=task_runtime,
                    model_access=model_access,
                )
                grant_locked.set()
                assert spend_locked.wait(timeout=10)
                return result

            def settle() -> None:
                close_old_connections()
                try:
                    with transaction.atomic():
                        SignalSpend.objects.for_team(self.team.id).select_for_update().get(signal_id=signal_id)
                        spend_locked.set()
                        assert grant_locked.wait(timeout=10)
                        record_llm_spend(
                            "late",
                            team_id=self.team.id,
                            signal_id=signal_id,
                            stage="research",
                            token_cost_microusd=2,
                            trial_grant_id=str(grant.id),
                        )
                finally:
                    close_old_connections()

            def create_run() -> None:
                close_old_connections()
                try:
                    task.create_run()
                finally:
                    close_old_connections()

            with (
                patch.object(TaskTrialAdmission, "bind", bind),
                patch("products.tasks.backend.models.execute_after_commit", side_effect=transaction.on_commit),
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                first, second = pool.submit(settle), pool.submit(create_run)
                first.result(timeout=20)
                second.result(timeout=20)
            grant.refresh_from_db()
            assert trial_usage(grant).spend_microusd == 40_003
            assert task.runs.count() == 1
