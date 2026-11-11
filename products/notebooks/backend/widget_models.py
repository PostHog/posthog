from posthog.enums import LabeledStrEnum

WIDGET_MODEL_CHOICES = (
    "claude-haiku-4-5",
    "claude-sonnet-4-6",
    "claude-sonnet-5",
    "claude-opus-5",
)

DEFAULT_WIDGET_MODEL = "claude-sonnet-5"


# Each label repeats its value, because the API documents these choices as plain values.
class LifecycleStatus(LabeledStrEnum):
    AWAITING_GENERATION = "awaiting_generation", "awaiting_generation"
    GENERATING = "generating", "generating"
    BUILDING = "building", "building"
    READY = "ready", "ready"
    FAILED = "failed", "failed"
    INCOMPATIBLE = "incompatible", "incompatible"


MAX_WIDGET_PROMPT_LENGTH = 20_000
MAX_WIDGET_EFFECTIVE_PROMPT_LENGTH = 50_000
