from posthog.test.base import BaseTest

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.entitlements.contracts import EntitlementChange, Entitlements
from posthog.entitlements.execution import execute_entitlement_reactor
from posthog.entitlements.registry import get_entitlement_reactor_registry
from posthog.models.organization import Organization
from posthog.models.organization_entitlement_applied_state import OrganizationEntitlementAppliedState

from products.logs.backend.entitlement_reactors import LOGS_RETENTION_REACTOR_KEY
from products.logs.backend.models import LogsRetentionRule

PAID_RETENTION = Entitlements.from_features([{"key": "logs_retention_30d"}])
NO_PAID_RETENTION = Entitlements()


class TestLogsRetentionReactorRegistration(SimpleTestCase):
    def test_registry_loads_the_logs_retention_reactor(self) -> None:
        get_entitlement_reactor_registry.cache_clear()
        self.addCleanup(get_entitlement_reactor_registry.cache_clear)

        (reactor,) = get_entitlement_reactor_registry().selected([LOGS_RETENTION_REACTOR_KEY])

        assert reactor.key == "logs-retention"
        assert reactor.feature_keys == frozenset({"logs_retention_30d"})


class TestLogsRetentionReactor(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.logs_settings = {"retention_days": 30, "json_parse_logs": True}
        self.team.save()
        self.rule = LogsRetentionRule.objects.create(
            team=self.team,
            name="keep api logs",
            enabled=True,
            config={"retention_days": 90, "filter_group": {"type": "AND", "values": []}},
        )
        (self.reactor,) = get_entitlement_reactor_registry().selected([LOGS_RETENTION_REACTOR_KEY])

    def assert_retention(self, team_days: int, rule_days: int, rule_version: int) -> None:
        self.team.refresh_from_db()
        self.rule.refresh_from_db()
        assert self.team.logs_settings == {"retention_days": team_days, "json_parse_logs": True}
        assert self.rule.config["retention_days"] == rule_days
        assert self.rule.version == rule_version

    @parameterized.expand(
        [
            ("revoked", PAID_RETENTION, NO_PAID_RETENTION, (14, 14, 2)),
            ("no_previous", None, NO_PAID_RETENTION, (14, 14, 2)),
            ("previous_already_lacked_feature", NO_PAID_RETENTION, NO_PAID_RETENTION, (14, 14, 2)),
            ("entitled", NO_PAID_RETENTION, PAID_RETENTION, (30, 90, 1)),
        ]
    )
    def test_react_matches_current_entitlements_and_is_idempotent(
        self,
        _name: str,
        previous: Entitlements | None,
        current: Entitlements,
        expected: tuple[int, int, int],
    ) -> None:
        change = EntitlementChange(organization_id=str(self.organization.id), previous=previous, current=current)

        self.reactor.react(change)
        self.assert_retention(*expected)
        self.reactor.react(change)
        self.assert_retention(*expected)

    def test_execution_resets_retention_and_advances_the_checkpoint(self) -> None:
        organization_id = str(self.organization.id)
        Organization.objects.filter(id=organization_id).update(available_product_features=[{"key": "surveys"}])
        checkpoint = OrganizationEntitlementAppliedState.objects.create(
            organization=self.organization,
            reactor_key=LOGS_RETENTION_REACTOR_KEY,
            snapshot=PAID_RETENTION.to_snapshot(),
            applied_at=timezone.now(),
        )

        assert execute_entitlement_reactor(organization_id, LOGS_RETENTION_REACTOR_KEY).applied
        self.assert_retention(14, 14, 2)
        checkpoint.refresh_from_db()
        assert checkpoint.snapshot == []
        assert not execute_entitlement_reactor(organization_id, LOGS_RETENTION_REACTOR_KEY).applied
