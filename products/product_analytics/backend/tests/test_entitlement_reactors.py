from datetime import date
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db.models.query import QuerySet
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.entitlements.contracts import Entitlements, FeatureEntry
from posthog.entitlements.execution import execute_entitlement_reactor
from posthog.entitlements.registry import get_entitlement_reactor_registry
from posthog.models.events_plan_deletion import PlanDeletionState, TeamEventsPlanDeletion
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_entitlement_applied_state import OrganizationEntitlementAppliedState
from posthog.models.team import Team

from products.product_analytics.backend.entitlement_reactors import EVENTS_RETENTION_REACTOR_KEY

STANDARD_RETENTION: FeatureEntry = {"key": "product_analytics_standard_data_retention"}
SEVEN_YEAR_PLAN: list[FeatureEntry] = [{"key": "product_analytics_data_retention", "limit": 7, "unit": "years"}]
SEVEN_YEAR_STANDARD_PLAN: list[FeatureEntry] = [*SEVEN_YEAR_PLAN, STANDARD_RETENTION]
TWO_YEAR_PLAN: list[FeatureEntry] = [{"key": "product_analytics_data_retention", "limit": 2, "unit": "years"}]
TWO_YEAR_STANDARD_PLAN: list[FeatureEntry] = [*TWO_YEAR_PLAN, STANDARD_RETENTION]
PASS_BEFORE = PlanDeletionState(months=84, next_deletion_on=date(2026, 12, 3))
PUSHED_PASS = PlanDeletionState(months=24, next_deletion_on=date(2027, 3, 3))


class TestEventsRetentionReactorRegistration(SimpleTestCase):
    def test_registry_loads_the_events_retention_reactor(self) -> None:
        get_entitlement_reactor_registry.cache_clear()
        self.addCleanup(get_entitlement_reactor_registry.cache_clear)

        (reactor,) = get_entitlement_reactor_registry().selected([EVENTS_RETENTION_REACTOR_KEY])

        assert reactor.key == "events-retention"
        assert reactor.feature_keys == frozenset(
            {"product_analytics_data_retention", "product_analytics_standard_data_retention"}
        )


@override_settings(CLOUD_DEPLOYMENT="US", EVENTS_DATA_RETENTION_ENFORCED=True)
class TestEventsRetentionReactor(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        TeamEventsPlanDeletion.objects.create(
            team=self.team, months=PASS_BEFORE.months, next_deletion_on=PASS_BEFORE.next_deletion_on
        )
        traveller = time_machine.travel("2026-11-20T18:00:00Z", tick=False)
        traveller.start()
        self.addCleanup(traveller.stop)
        cloud_patch = patch("posthog.models.events_plan_deletion.is_cloud", return_value=True)
        cloud_patch.start()
        self.addCleanup(cloud_patch.stop)
        capture_patch = patch("posthog.models.events_plan_deletion.ph_scoped_capture")
        self.scoped_capture = capture_patch.start()
        self.addCleanup(capture_patch.stop)

    def create_checkpoint(
        self, previous: list[FeatureEntry], current: list[FeatureEntry], team_months: int
    ) -> OrganizationEntitlementAppliedState:
        Organization.objects.filter(id=self.organization.id).update(available_product_features=current)
        Team.objects.filter(id=self.team.id).update(event_retention_months=team_months)
        return OrganizationEntitlementAppliedState.objects.create(
            organization=self.organization,
            reactor_key=EVENTS_RETENTION_REACTOR_KEY,
            snapshot=Entitlements.from_features(previous).to_snapshot(),
            applied_at=timezone.now(),
        )

    def captured(self) -> list[dict[str, Any]]:
        return [call.kwargs for call in self.scoped_capture.return_value.__enter__.return_value.call_args_list]

    def assert_teams_and_pass(self, team_months: int, pass_state: PlanDeletionState) -> None:
        self.team.refresh_from_db()
        assert self.team.event_retention_months == team_months
        assert TeamEventsPlanDeletion.objects.get(team=self.team).state == pass_state

    @parameterized.expand(
        [
            ("downgrade", SEVEN_YEAR_PLAN, TWO_YEAR_PLAN, 84, 24, PUSHED_PASS, True),
            ("billing_already_applied", SEVEN_YEAR_PLAN, TWO_YEAR_PLAN, 24, 24, PASS_BEFORE, False),
            ("downgrade_from_standard_retention", SEVEN_YEAR_STANDARD_PLAN, TWO_YEAR_PLAN, 84, 24, PASS_BEFORE, False),
            ("standard_retention_only", TWO_YEAR_PLAN, TWO_YEAR_STANDARD_PLAN, 84, 84, PASS_BEFORE, False),
            ("first_sync", [], TWO_YEAR_PLAN, 84, 24, PASS_BEFORE, False),
        ]
    )
    def test_execution_acts_on_plan_months_changes_and_reports_only_new_shortenings(
        self,
        _name: str,
        previous: list[FeatureEntry],
        current: list[FeatureEntry],
        team_months: int,
        expected_team_months: int,
        expected_pass: PlanDeletionState,
        notified: bool,
    ) -> None:
        organization_id = str(self.organization.id)
        checkpoint = self.create_checkpoint(previous, current, team_months)

        with self.captureOnCommitCallbacks(execute=True):
            assert execute_entitlement_reactor(organization_id, EVENTS_RETENTION_REACTOR_KEY).applied
            assert not execute_entitlement_reactor(organization_id, EVENTS_RETENTION_REACTOR_KEY).applied

        self.assert_teams_and_pass(expected_team_months, expected_pass)
        checkpoint.refresh_from_db()
        assert checkpoint.snapshot == Entitlements.from_features(current).to_snapshot()
        assert self.captured() == (
            [
                {
                    "distinct_id": self.user.distinct_id,
                    "event": "events retention period shortened",
                    "properties": {
                        "organization_name": self.organization.name,
                        "retention_months": 24,
                        "deletion_scheduled_on": "2027-03-03",
                        "previous_retention_months": 84,
                        "$update_person_last_seen_at": False,
                    },
                    "groups": {"organization": organization_id},
                }
            ]
            if notified
            else []
        )

    def test_a_failed_checkpoint_write_rolls_back_the_downgrade_and_sends_no_notice(self) -> None:
        checkpoint = self.create_checkpoint(SEVEN_YEAR_PLAN, TWO_YEAR_PLAN, 84)
        update_or_create = QuerySet.update_or_create

        def fail_checkpoint_write(queryset: QuerySet, *args: Any, **kwargs: Any) -> Any:
            if queryset.model is OrganizationEntitlementAppliedState:
                raise RuntimeError("Checkpoint write failed")
            return update_or_create(queryset, *args, **kwargs)

        with (
            self.captureOnCommitCallbacks(execute=True),
            patch.object(QuerySet, "update_or_create", fail_checkpoint_write),
            self.assertRaisesMessage(RuntimeError, "Checkpoint write failed"),
        ):
            execute_entitlement_reactor(str(self.organization.id), EVENTS_RETENTION_REACTOR_KEY)

        self.assert_teams_and_pass(84, PASS_BEFORE)
        checkpoint.refresh_from_db()
        assert checkpoint.snapshot == Entitlements.from_features(SEVEN_YEAR_PLAN).to_snapshot()
        assert self.captured() == []
