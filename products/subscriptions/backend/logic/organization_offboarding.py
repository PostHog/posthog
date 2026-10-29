from django.db.models import QuerySet

from posthog.organization_offboarding_types import OffboardingResource

from products.subscriptions.backend.models.subscription import Subscription


class SubscriptionOffboarding:
    def __init__(self, organization_id: str, user_id: int) -> None:
        self.organization_id = organization_id
        self.user_id = user_id

    def _subscriptions(self) -> QuerySet[Subscription]:
        return Subscription.objects.filter(team__organization_id=self.organization_id, deleted=False)

    def resources(self) -> list[OffboardingResource]:
        return [
            OffboardingResource(
                id=f"subscription:{subscription.pk}",
                kind="subscription",
                name=subscription.title or "Untitled subscription",
                team_id=subscription.team_id,
                project_name=subscription.team.name,
                created_at=subscription.created_at,
                url=f"/project/{subscription.team_id}/subscriptions/{subscription.pk}",
            )
            for subscription in self._subscriptions()
            .filter(created_by_id=self.user_id, enabled=True)
            .select_related("team")
        ]

    def disable(self, keep: set[str], email: str) -> None:
        subscriptions = self._subscriptions()
        for subscription in subscriptions.filter(created_by_id=self.user_id, enabled=True):
            if f"subscription:{subscription.pk}" not in keep:
                subscription.enabled = False
                subscription.save(update_fields=["enabled"])

        for subscription in subscriptions.filter(
            target_type=Subscription.SubscriptionTarget.EMAIL, target_value__icontains=email
        ):
            recipients = [recipient.strip() for recipient in subscription.target_value.split(",")]
            remaining = [recipient for recipient in recipients if recipient.casefold() != email.casefold()]
            if remaining != recipients:
                subscription.target_value = ",".join(remaining)
                if not remaining:
                    subscription.enabled = False
                subscription.save(update_fields=["target_value", "enabled"])
