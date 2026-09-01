from posthog.jwt import PosthogJwtAudience
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

# Minted by the plugin server's "Create AI task" workflow action, verified by the
# workflow_tasks endpoint. Empty (so disabled) in production until provisioned.
TASKS_CREATE_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.TASKS_CREATE,
    settings_name="TASKS_CREATE_JWT_SECRETS",
)

# Same key as TASKS_CREATE_PURPOSE (both mint from the plugin server for a workflow step), on its
# own audience: the scoped-JWT rule is one key per caller/callee surface, so a token minted for
# one step must not verify at the other's endpoint. Mirrors WORKFLOWS_CANCEL_INVOCATIONS /
# WORKFLOWS_CANCEL_BATCH in posthog/plugins/plugin_server_api.py, which share a key the same way.
WORKFLOW_SCOUT_RUN_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.WORKFLOW_SCOUT_RUN,
    settings_name="TASKS_CREATE_JWT_SECRETS",
)
