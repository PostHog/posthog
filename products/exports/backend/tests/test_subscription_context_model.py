from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Model
from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping.manager import TeamScopeError

from products.dashboards.backend.models.dashboard import Dashboard
from products.exports.backend.models import Subscription, SubscriptionContext
from products.product_analytics.backend.facade.models import Insight


class TestSubscriptionContextModel(BaseTest):
    def _subscription(self) -> Subscription:
        return Subscription.objects.create(
            team=self.team,
            prompt="Summarize this report",
            target_type=Subscription.SubscriptionTarget.EMAIL,
            target_value="test@example.com",
            frequency=Subscription.SubscriptionFrequency.WEEKLY,
            start_date=timezone.now(),
        )

    def _dashboard(self) -> Dashboard:
        return Dashboard.objects.create(team=self.team, name="Context dashboard", created_by=self.user)

    def _insight(self) -> Insight:
        return Insight.objects.create(team=self.team, name="Context insight", created_by=self.user)

    def _create_context(self, **kwargs: object) -> SubscriptionContext:
        defaults: dict[str, object] = {
            "team": self.team,
            "subscription": self._subscription(),
            "dashboard": self._dashboard(),
        }
        defaults.update(kwargs)
        return SubscriptionContext.objects.for_team(self.team.id).create(**defaults)

    def test_exactly_one_target_is_required(self) -> None:
        subscription = self._subscription()

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create_context(subscription=subscription, dashboard=None)

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create_context(subscription=subscription, insight=self._insight())

    @parameterized.expand([("dashboard",), ("insight",)])
    def test_duplicate_target_for_subscription_is_rejected(self, target_kind: str) -> None:
        subscription = self._subscription()
        target = self._dashboard() if target_kind == "dashboard" else self._insight()
        target_kwargs: dict[str, Dashboard | Insight | None] = {target_kind: target}
        if target_kind == "insight":
            target_kwargs["dashboard"] = None
        self._create_context(subscription=subscription, **target_kwargs)

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create_context(subscription=subscription, **target_kwargs)

    def test_for_team_returns_only_its_contexts(self) -> None:
        other_team = self.organization.teams.create(name="other")
        mine = self._create_context()
        other_subscription = Subscription.objects.create(
            team=other_team,
            prompt="Summarize another report",
            target_type=Subscription.SubscriptionTarget.EMAIL,
            target_value="other@example.com",
            frequency=Subscription.SubscriptionFrequency.WEEKLY,
            start_date=timezone.now(),
        )
        other_dashboard = Dashboard.objects.create(team=other_team, name="Other dashboard", created_by=self.user)
        SubscriptionContext.objects.for_team(other_team.id).create(
            team=other_team,
            subscription=other_subscription,
            dashboard=other_dashboard,
        )

        self.assertEqual(list(SubscriptionContext.objects.for_team(self.team.id)), [mine])

    def test_rejects_a_target_from_another_team(self) -> None:
        other_team = self.organization.teams.create(name="other")
        other_dashboard = Dashboard.objects.create(team=other_team, name="Other dashboard", created_by=self.user)

        with self.assertRaisesRegex(ValidationError, "target must belong"):
            self._create_context(dashboard=other_dashboard)

    def test_unscoped_read_fails_closed(self) -> None:
        self._create_context()

        with self.assertRaises(TeamScopeError):
            list(SubscriptionContext.objects.all())

    @parameterized.expand([("subscription",), ("dashboard",), ("insight",)])
    def test_target_delete_cascades_to_context(self, target_kind: str) -> None:
        target: Model
        if target_kind == "subscription":
            target = self._subscription()
            context = self._create_context(subscription=target)
        elif target_kind == "dashboard":
            target = self._dashboard()
            context = self._create_context(dashboard=target)
        else:
            target = self._insight()
            context = self._create_context(dashboard=None, insight=target)

        target.delete()

        self.assertFalse(SubscriptionContext.objects.unscoped().filter(pk=context.pk).exists())
