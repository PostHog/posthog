from posthog.jwt import PosthogJwtAudience
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

# Minted by the plugin server's "Create AI task" workflow action, verified by the
# workflow_tasks endpoint. Empty (so disabled) in production until provisioned.
TASKS_CREATE_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.TASKS_CREATE,
    settings_name="TASKS_CREATE_JWT_SECRETS",
)
