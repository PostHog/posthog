from posthog.ingress.contracts import DeliveryOwnership
from posthog.ingress.dispatch.database import bounded_statement_timeout
from posthog.integrations import IntegrationManager

# The timeout router needs the model class, but all integration reads go through the SDK.
from posthog.models.integration import Integration  # nosemgrep: semgrep.rules.devex.integration-model-through-sdk


def workspace_ownership(organization_id: str) -> DeliveryOwnership:
    with bounded_statement_timeout(800, models=[Integration]):
        held_here = IntegrationManager.linear.oauth.exists_by_external_id(organization_id)
    return DeliveryOwnership.LOCAL if held_here else DeliveryOwnership.ELSEWHERE
