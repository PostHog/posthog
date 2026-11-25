from posthog.enums import LabeledStrEnum


class SlackSetupStepKey(LabeledStrEnum):
    AI_CONSENT = "ai_consent", "AI data processing"
    DEFAULT_PROJECT = "default_project", "Default project"
    CHANNELS = "channels", "Channels"


class SlackReactionKind(LabeledStrEnum):
    WORKING = "working", "Working"
    DONE = "done", "Done"
    ERROR = "error", "Error"
    POLITE = "polite", "Thank-you reaction"


class SlackUntaggedMode(LabeledStrEnum):
    """What PostHog does with a message that does not tag it. The values match ``UntaggedFollowupMode``.

    The labels differ from that model enum on purpose: drf-spectacular cannot tell apart two classes with
    the same values and labels, and then names neither in the OpenAPI schema."""

    AUTO = "auto", "Answer automatically"
    ASK = "ask", "Ask first"
    NEVER = "never", "Never answer"


class SlackSetupEntry(LabeledStrEnum):
    SLACK_PAGE = "slack_page", "The Slack page in PostHog"
    OTHER = "other", "Another place, such as a channel picker"
