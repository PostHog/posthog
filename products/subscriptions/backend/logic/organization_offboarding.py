from django.core.exceptions import ValidationError
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
                destination_type=subscription.target_type,
                destination=subscription.recipient_label,
                url=f"/project/{subscription.team_id}/subscriptions/{subscription.pk}",
            )
            for subscription in self._subscriptions()
            .filter(created_by_id=self.user_id, enabled=True)
            .select_related("team")
        ]

    def update(self, resource_id: str, enabled: bool) -> None:
        identifier = Subscription._meta.pk.to_python(resource_id.removeprefix("subscription:"))
        subscription = (
            self._subscriptions().select_for_update().filter(pk=identifier, created_by_id=self.user_id).first()
        )
        if subscription is None:
            raise ValidationError("Subscription not found for this member.")
        if subscription.enabled != enabled:
            subscription.enabled = enabled
            subscription.save(update_fields=["enabled"])
