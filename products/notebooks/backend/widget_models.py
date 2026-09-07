from posthog.dataclasses import frozen

WIDGET_MODEL_CHOICES = (
    "claude-haiku-4-5",
    "claude-sonnet-4-6",
    "claude-sonnet-5",
    "claude-opus-5",
)

DEFAULT_WIDGET_MODEL = "claude-sonnet-4-6"

WIDGET_LIFECYCLE_STATUS_CHOICES = (
    "awaiting_generation",
    "generating",
    "building",
    "ready",
    "failed",
    "incompatible",
)

MAX_WIDGET_PROMPT_LENGTH = 20_000
MAX_WIDGET_EFFECTIVE_PROMPT_LENGTH = 50_000


@frozen
class WidgetPermissions:
    notebook_data: bool = True
    hogql_queries: bool = False
    tool_calls: bool = False


DEFAULT_WIDGET_PERMISSIONS = WidgetPermissions()
