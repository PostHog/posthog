from posthog.jwt import PosthogJwtAudience
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

# Minted by the plugin server's "Create AI task" workflow action, verified by the
# workflow_tasks endpoint. Empty (so disabled) in production until provisioned.
TASKS_CREATE_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.TASKS_CREATE,
    settings_name="TASKS_CREATE_JWT_SECRETS",
)

# Minted by the plugin server's "Run scout" workflow action, verified by the
# workflow_scout_runs endpoint. Empty (so disabled) in production until provisioned.
SIGNALS_SCOUT_RUN_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.SIGNALS_SCOUT_RUN,
    settings_name="SIGNALS_SCOUT_RUN_JWT_SECRETS",
)
