from posthog.enums import LabeledStrEnum


# The labels repeat the values because the published OpenAPI enum lists these exact pairs.
class TaskChannelWriteType(LabeledStrEnum):
    PUBLIC = "public", "public"
    PRIVATE = "private", "private"
