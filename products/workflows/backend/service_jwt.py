from posthog.jwt import PosthogJwtAudience
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

# Minted by the plugin server's "Create AI task" workflow action, verified by the
# workflow_tasks endpoint. Empty (so disabled) in production until provisioned.
TASKS_CREATE_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.TASKS_CREATE,
    settings_name="TASKS_CREATE_JWT_SECRETS",
)

# A dedicated key, not TASKS_CREATE_PURPOSE's: both mint from the plugin server for a workflow
# step, but the scoped-JWT rule is narrowest scope, mint a new key for a new use case rather than
# widen an existing one's — a leak of one can't forge the other's calls, on top of the audience
# claim already blocking a legitimate token from replaying at the wrong endpoint.
WORKFLOW_SCOUT_RUN_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.WORKFLOW_SCOUT_RUN,
    settings_name="WORKFLOW_SCOUT_RUN_JWT_SECRETS",
)
