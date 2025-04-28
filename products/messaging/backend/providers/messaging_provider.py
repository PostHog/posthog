from typing import Optional

from posthog.models import Integration, User
from posthog.api.integration import IntegrationSerializer


class MessagingProvider:
    def create_integration(
        self, kind: str, integration_id: str, config: dict, team_id: int, created_by: Optional[User] = None
    ) -> Integration:
        # Use IntegrationSerializer to reuse its validation
        serializer = IntegrationSerializer(
            data={
                "kind": kind,
                "integration_id": integration_id,
                "config": config,
                "team_id": team_id,
                "created_by": created_by.id if created_by else None,
            }
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def update_integration(self, kind: str, integration_id: str, team_id: int, updated_config: dict):
        integration = Integration.objects.get(kind=kind, integration_id=integration_id, team_id=team_id)
        # Merge the new config with existing config
        updated_config = {**integration.config, **updated_config}

        # Use IntegrationSerializer to reuse its validation
        serializer = IntegrationSerializer(integration, data={"config": updated_config}, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return serializer.instance
