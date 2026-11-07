from posthog.enums import LabeledStrEnum


class SidebarPage(LabeledStrEnum):
    ANALYTICS_ALL = "analytics_all", "View all"
    ANALYTICS_MINE = "analytics_mine", "My work"
    COLLECTIONS = "collections", "Collections"
    ALERTS = "alerts", "Alerts"
    SUBSCRIPTIONS = "subscriptions", "Subscriptions"
    PRODUCT_ANALYTICS = "product_analytics", "Product analytics"
    WEB_ANALYTICS = "web_analytics", "Web analytics"
    SQL_EDITOR = "sql_editor", "SQL editor"
    NEW_INSIGHT = "new_insight", "New insight"


class SidebarIcon(LabeledStrEnum):
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


class SidebarListSource(LabeledStrEnum):
    PINNED = "pinned", "Items the person pinned"
    RECENTS = "recents", "Items the person opened recently"
    BY_POSTHOG = "by_posthog", "Ready-made analytics by PostHog"


class SidebarButtonVariant(LabeledStrEnum):
    DEFAULT = "default", "Default"
    PRIMARY = "primary", "Primary"
    OUTLINE = "outline", "Outline"
