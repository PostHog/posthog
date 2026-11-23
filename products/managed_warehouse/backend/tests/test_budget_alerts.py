from datetime import UTC, datetime
from decimal import Decimal

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.models import Organization, OrganizationMembership, User

from products.managed_warehouse.backend import tasks
from products.managed_warehouse.backend.facade.contracts import ControlPlaneUnavailableError
from products.managed_warehouse.backend.logic import budget_alerts
from products.managed_warehouse.backend.logic.console_usage import SpendEstimate
from products.managed_warehouse.backend.models import ManagedWarehouseOrgSettings

JULY = datetime(2026, 7, 15, 12, tzinfo=UTC)
AUGUST = datetime(2026, 8, 2, 12, tzinfo=UTC)
_ESTIMATE = "products.managed_warehouse.backend.logic.budget_alerts.estimate_month_to_date_spend"
_ENABLED = "products.managed_warehouse.backend.logic.budget_alerts.is_console_enabled"
_EMAIL = "products.managed_warehouse.backend.logic.budget_alerts.EmailMessage"


def _estimate(total: str, now: datetime) -> SpendEstimate:
    return SpendEstimate(month_start=now.date().replace(day=1), total_usd=Decimal(total), forecast_usd=Decimal("300"))


class TestBudgetAlerts(BaseTest):
    def setUp(self):
        super().setUp()
        self.row = ManagedWarehouseOrgSettings.objects.create(
            organization=self.organization, monthly_budget_usd=Decimal("100")
        )
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.OWNER
        )
        enabled = patch(_ENABLED, return_value=True)
        enabled.start()
        self.addCleanup(enabled.stop)
        email = patch(_EMAIL)
        self.email_cls = email.start()
        self.addCleanup(email.stop)

    def _run(self, total: str, now: datetime) -> int:
        with patch(_ESTIMATE, return_value=_estimate(total, now)):
            return int(budget_alerts.check_organization_budget(str(self.organization.id), now=now))

    def _subjects(self) -> list[str]:
        return [call.kwargs["subject"] for call in self.email_cls.call_args_list]

    def test_threshold_progression_sends_each_threshold_once_and_resets_next_month(self):
        assert self._run("40", JULY) == 0
        assert self._run("55", JULY) == 1
        assert self._run("60", JULY) == 0
        assert self._run("85", JULY) == 1
        assert self._run("90", JULY) == 0
        assert self._subjects() == [
            "Your warehouse spend reached 50% of your monthly budget",
            "Your warehouse spend reached 80% of your monthly budget",
        ]
        self.row.refresh_from_db()
        assert (self.row.budget_alert_month, self.row.budget_alert_threshold) == (JULY.date().replace(day=1), 80)

        assert self._run("55", AUGUST) == 1
        assert len(self.email_cls.call_args_list) == 3

    def test_claim_allows_only_one_sender_per_threshold(self):
        month = JULY.date().replace(day=1)
        assert budget_alerts._claim_alert(self.row.pk, Decimal("100"), month, 80) is True
        assert budget_alerts._claim_alert(self.row.pk, Decimal("100"), month, 80) is False
        assert budget_alerts._claim_alert(self.row.pk, Decimal("100"), month, 50) is False
        assert budget_alerts._claim_alert(self.row.pk, Decimal("100"), month, 100) is True
        # A budget changed since the row was read does not get the stale claim.
        assert budget_alerts._claim_alert(self.row.pk, Decimal("50"), AUGUST.date().replace(day=1), 50) is False

    def test_unset_budget_is_skipped(self):
        self.row.monthly_budget_usd = None
        self.row.save()
        with patch(_ESTIMATE) as estimate:
            assert budget_alerts.check_organization_budget(str(self.organization.id), now=JULY) is False
        estimate.assert_not_called()

    def test_disabled_warehouse_is_skipped(self):
        with patch(_ENABLED, return_value=False), patch(_ESTIMATE) as estimate:
            assert budget_alerts.check_organization_budget(str(self.organization.id), now=JULY) is False
        estimate.assert_not_called()

    def test_fan_out_enqueues_one_task_per_eligible_org(self):
        done = Organization.objects.create(name="Done")
        ManagedWarehouseOrgSettings.objects.create(
            organization=done,
            monthly_budget_usd=Decimal("100"),
            budget_alert_month=JULY.date().replace(day=1),
            budget_alert_threshold=100,
        )
        ManagedWarehouseOrgSettings.objects.create(organization=Organization.objects.create(name="NoBudget"))
        partial = Organization.objects.create(name="Partial")
        ManagedWarehouseOrgSettings.objects.create(
            organization=partial,
            monthly_budget_usd=Decimal("100"),
            budget_alert_month=JULY.date().replace(day=1),
            budget_alert_threshold=80,
        )
        with (
            time_machine.travel(JULY, tick=False),
            patch.object(tasks.check_managed_warehouse_budget_for_org, "delay") as delay,
        ):
            tasks.check_managed_warehouse_budgets()
        assert {c.args[0] for c in delay.call_args_list} == {str(self.organization.id), str(partial.id)}

    def test_control_plane_error_propagates_from_the_per_org_check(self):
        with patch(_ESTIMATE, side_effect=ControlPlaneUnavailableError("down")):
            with self.assertRaises(ControlPlaneUnavailableError):
                budget_alerts.check_organization_budget(str(self.organization.id), now=JULY)
        self.row.refresh_from_db()
        assert self.row.budget_alert_threshold is None

    def test_budget_change_allows_a_new_email_at_the_same_threshold(self):
        assert self._run("55", JULY) == 1
        ManagedWarehouseOrgSettings.objects.filter(pk=self.row.pk).update(
            monthly_budget_usd=Decimal("200"), budget_alert_month=None, budget_alert_threshold=None
        )
        assert self._run("110", JULY) == 1
        keys = [call.kwargs["campaign_key"] for call in self.email_cls.call_args_list]
        assert len(keys) == 2 and keys[0] != keys[1]

    def test_email_goes_to_admins_and_owners_only(self):
        admin = User.objects.create_user("admin@example.com", "pw", "Admin")
        member = User.objects.create_user("member@example.com", "pw", "Member")
        self.organization.members.add(admin, member)
        OrganizationMembership.objects.filter(user=admin, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        message = MagicMock()
        self.email_cls.return_value = message

        self._run("85", JULY)

        recipients = {call.args[0].email for call in message.add_user_recipient.call_args_list}
        assert recipients == {self.user.email, "admin@example.com"}
        message.send.assert_called_once()
        context = self.email_cls.call_args.kwargs["template_context"]
        assert context["usage_url"].endswith(f"/project/{self.team.id}/warehouse/usage")

    def test_failed_send_keeps_the_claim_so_it_is_not_retried(self):
        self.email_cls.return_value.send.side_effect = RuntimeError("smtp down")
        assert self._run("55", JULY) == 1
        assert self._run("55", JULY) == 0
