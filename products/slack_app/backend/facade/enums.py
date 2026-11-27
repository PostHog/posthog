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


class SlackChannelQuestionMode(LabeledStrEnum):
    """What PostHog does with an untagged question in a channel. A channel only makes pickups stricter than each
    person's own mode, so it has no automatic choice. The values match ``UntaggedFollowupMode``."""

    ASK = "ask", "Asks before answering"
    NEVER = "never", "Only answers @-mentions"


class SlackThreadJoinMode(LabeledStrEnum):
    """What PostHog does when someone else tags it in a thread a person started. The values match
    ``ThreadJoinMode``, and the labels differ from it for the reason ``SlackUntaggedMode`` gives."""

    NEVER = "never", "Ignore others"
    ASK_PER_PERSON = "ask_per_person", "Ask for each person"
    ASK_PER_THREAD = "ask_per_thread", "Ask once for each thread"
    ALLOW = "allow", "Allow anyone"


class SlackSetupEntry(LabeledStrEnum):
    SLACK_PAGE = "slack_page", "The Slack page in PostHog"
    OTHER = "other", "Another place, such as a channel picker"
