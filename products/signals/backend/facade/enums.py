from posthog.enums import LabeledStrEnum


class ResearchAccessMode(LabeledStrEnum):
    CODE = "code", "Code research"
    REPOSITORY_DISCOVERY = "repository_discovery", "Repository discovery"
    DATA_ONLY = "data_only", "Project data research"
    BLOCKED = "blocked", "Research blocked"
