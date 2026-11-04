from posthog.organization_offboarding_types import OffboardingResource

from products.subscriptions.backend.logic.organization_offboarding import SubscriptionOffboarding


def list_member_offboarding_resources(organization_id: str, user_id: int) -> list[OffboardingResource]:
    return SubscriptionOffboarding(organization_id, user_id).resources()
