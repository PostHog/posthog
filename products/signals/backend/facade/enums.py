from posthog.enums import LabeledStrEnum


class ResearchAccessMode(LabeledStrEnum):
    CODE = "code", "Code research"
    DATA_ONLY = "data_only", "Project data research"
    BLOCKED = "blocked", "Research blocked"
