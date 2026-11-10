from posthog.enums import LabeledStrEnum


class CustomizationContext(LabeledStrEnum):
    ANALYTICS_SIDEBAR = "analytics_sidebar", "Analytics sidebar"


class FragmentIcon(LabeledStrEnum):
    LIST = "list", "List"
    PERSON = "person", "Person"
    PEOPLE = "people", "People"
    BOX = "box", "Box"
    BELL = "bell", "Bell"
    NOTIFICATION = "notification", "Notification"
    POSTHOG = "posthog", "PostHog logo"
    CHART = "chart", "Chart"
    DASHBOARD = "dashboard", "Dashboard"
    NOTEBOOK = "notebook", "Notebook"
    SQL = "sql", "SQL"
    STAR = "star", "Star"
    ROCKET = "rocket", "Rocket"
    TARGET = "target", "Target"
    TRENDING = "trending", "Trending"
    GLOBE = "globe", "Globe"
    SPARKLE = "sparkle", "Sparkle"
    BOLT = "bolt", "Bolt"
    FLAG = "flag", "Flag"
    WARNING = "warning", "Warning"


class FragmentButtonVariant(LabeledStrEnum):
    DEFAULT = "default", "Default"
    PRIMARY = "primary", "Primary"
    OUTLINE = "outline", "Outline"
