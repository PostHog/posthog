from posthog.jwt import PosthogJwtAudience
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

TASKS_CREATE_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.TASKS_CREATE,
    settings_name="TASKS_CREATE_JWT_SECRETS",
)
