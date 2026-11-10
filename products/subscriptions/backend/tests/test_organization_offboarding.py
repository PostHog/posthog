from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership, Team, User

from products.dashboards.backend.models.dashboard import Dashboard
from products.product_analytics.backend.facade.models import Insight
from products.subscriptions.backend.models.subscription import Subscription


class TestSubscriptionOffboarding(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.departing = User.objects.create_and_join(self.organization, "departing@example.com", None)
        self.url = f"/api/organizations/@current/members/{self.departing.uuid}/"

    def subscription(self, *, creator: User, recipients: str) -> Subscription:
        return Subscription.objects.create(
            team=self.team,
            created_by=creator,
            dashboard=Dashboard.objects.create(team=self.team, created_by=creator),
            title="Weekly report",
            target_type="email",
            target_value=recipients,
            frequency="daily",
            interval=1,
            start_date=timezone.now(),
        )

    def test_preview_lists_created_subscriptions_and_removal_preserves_them(self) -> None:
        own = self.subscription(creator=self.departing, recipients="other@example.com")
        others = self.subscription(creator=self.user, recipients="other@example.com")
        recipient = self.subscription(creator=self.user, recipients="DEPARTING@example.com,other@example.com")
        only_recipient = self.subscription(creator=self.user, recipients=self.departing.email)
        response = self.client.get(self.url + "offboarding_preview/")
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [f"subscription:{own.pk}"]
        assert response.json()[0]["url"] == f"/project/{self.team.pk}/subscriptions/{own.pk}"
        assert response.json()[0]["created_at"] is not None
        response = self.client.delete(self.url)
        assert response.status_code == 204
        for subscription in (own, others, recipient, only_recipient):
            subscription.refresh_from_db()
        assert own.enabled
        assert others.enabled
        assert recipient.enabled and recipient.target_value == "DEPARTING@example.com,other@example.com"
        assert only_recipient.enabled and only_recipient.target_value == self.departing.email

    @parameterized.expand([("dashboard",), ("insight",)])
    def test_preview_excludes_subscriptions_with_deleted_resources(self, kind: str) -> None:
        subscription = self.subscription(creator=self.departing, recipients="reports@example.com")
        if kind == "insight":
            subscription.dashboard = None
            subscription.insight = Insight.objects.create(team=self.team, created_by=self.departing)
            subscription.save(update_fields=["dashboard", "insight"])
        resource = subscription.dashboard if kind == "dashboard" else subscription.insight
        assert resource is not None
        assert [item["id"] for item in self.client.get(self.url + "offboarding_preview/").json()] == [
            f"subscription:{subscription.pk}"
        ]

        resource.deleted = True
        resource.save(update_fields=["deleted"])

        response = self.client.get(self.url + "offboarding_preview/")
        assert response.status_code == 200
        assert response.json() == []
        subscription.refresh_from_db()
        assert subscription.enabled

    def test_untitled_subscriptions_use_the_resource_name(self) -> None:
        subscription = self.subscription(creator=self.departing, recipients="reports@example.com")
        subscription.title = ""
        subscription.save(update_fields=["title"])
        assert subscription.dashboard is not None
        subscription.dashboard.name = "Weekly product usage"
        subscription.dashboard.save(update_fields=["name"])
        response = self.client.get(self.url + "offboarding_preview/")
        assert response.status_code == 200
        assert response.json()[0]["name"] == "Weekly product usage"

    @parameterized.expand(
        [
            ("email", "first@example.com,second@example.com", "first@example.com,second@example.com"),
            ("slack", "C123|#reports", "C123|#reports"),
            ("teams", "https://example.com/webhook/fake-secret", "example.com"),
        ]
    )
    def test_subscription_destinations_exclude_webhook_credentials(
        self, target_type: str, target_value: str, expected: str
    ) -> None:
        subscription = self.subscription(creator=self.departing, recipients=target_value)
        subscription.target_type = target_type
        subscription.save(update_fields=["target_type"])
        response = self.client.get(self.url + "offboarding_preview/")
        assert response.status_code == 200
        assert response.json()[0]["destination_type"] == target_type
        assert response.json()[0]["destination"] == expected
        assert "fake-secret" not in response.content.decode()

    def test_kept_subscriptions_preserve_recipients(self) -> None:
        kept = self.subscription(creator=self.departing, recipients=f"{self.departing.email},other@example.com")
        disabled = self.subscription(creator=self.departing, recipients="other@example.com")
        response = self.client.patch(
            f"/api/projects/{self.team.pk}/subscriptions/{disabled.pk}/",
            {"enabled": False},
            format="json",
        )
        assert response.status_code == 200
        kept.refresh_from_db()
        disabled.refresh_from_db()
        assert kept.enabled and kept.target_value == f"{self.departing.email},other@example.com"
        assert not disabled.enabled
        assert disabled.target_value == "other@example.com"

    def test_offboarding_does_not_change_subscriptions_in_another_organization(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other organization"))
        subscription = self.subscription(creator=self.departing, recipients=self.departing.email)
        subscription.team = other_team
        subscription.save(update_fields=["team"])
        assert self.client.get(self.url + "offboarding_preview/").json() == []
        assert self.client.delete(self.url).status_code == 204
        subscription.refresh_from_db()
        assert subscription.enabled
        assert subscription.target_value == self.departing.email

    def test_ai_subscriptions_are_included(self) -> None:
        subscription = self.subscription(creator=self.departing, recipients="reports@example.com")
        subscription.prompt = "Summarize weekly product usage"
        subscription.dashboard = None
        subscription.save(update_fields=["prompt", "dashboard"])
        response = self.client.get(self.url + "offboarding_preview/")
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [f"subscription:{subscription.pk}"]

    def test_self_leave_preserves_subscriptions_in_other_projects(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        subscription = self.subscription(creator=self.departing, recipients="private@example.com")
        subscription.team = other_team
        subscription.save(update_fields=["team"])
        self.client.force_login(self.departing)
        assert self.client.get(self.url + "offboarding_preview/").json() == []
        assert self.client.delete(self.url).status_code == 204
        subscription.refresh_from_db()
        assert subscription.enabled

    def test_subscription_changes_save_before_removal_and_can_be_reversed(self) -> None:
        subscription = self.subscription(creator=self.departing, recipients="reports@example.com")
        for enabled in (False, True):
            response = self.client.patch(
                f"/api/projects/{self.team.pk}/subscriptions/{subscription.pk}/",
                {"enabled": enabled, "send_test_now": False},
                format="json",
            )
            assert response.status_code == 200, response.json()
            subscription.refresh_from_db()
            assert subscription.enabled == enabled
            assert self.organization.members.filter(pk=self.departing.pk).exists()
        assert self.client.delete(self.url).status_code == 204
        subscription.refresh_from_db()
        assert subscription.enabled
