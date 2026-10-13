"""Enumerations the product_analytics models use.

Consumers that only need a variable type read it from here and do not need the model class. The
model keeps it as a class attribute (``InsightVariable.Type``) so existing call sites are
unchanged. In an annotation the class attribute is not a valid type, so annotate with
``InsightVariableType`` directly.
"""

from posthog.enums import LabeledStrEnum


class InsightVariableType(LabeledStrEnum):
    STRING = "String", "String"
    NUMBER = "Number", "Number"
    BOOLEAN = "Boolean", "Boolean"
    LIST = "List", "List"
    DATE = "Date", "Date"


class InsightDataCheckKey(LabeledStrEnum):
    INTERNAL_USERS = "internal_users", "Internal and test users"
    LOCAL_DEVELOPMENT = "local_development", "Local development events"
    BOT_TRAFFIC = "bot_traffic", "Bot and crawler traffic"
    DUPLICATE_EVENTS = "duplicate_events", "Events sent twice"


class InsightDataCheckLevel(LabeledStrEnum):
    PASSED = "passed", "Passed"
    WARNING = "warning", "Warning"
    PROBLEM = "problem", "Problem"
    SKIPPED = "skipped", "Not checked"


class InsightDataCheckAction(LabeledStrEnum):
    FILTER_INTERNAL_USERS = "filter_internal_users", "Turn on the internal and test users filter for the insight"
    OPEN_FILTER_SETTINGS = "open_filter_settings", "Change the project's internal and test users filter"


class InsightDataChecksStatus(LabeledStrEnum):
    PASSED = "passed", "No data issues found"
    WARNING = "warning", "A check found a small issue"
    PROBLEM = "problem", "A check found a large issue"
    NO_EVENTS = "no_events", "No events to check"
    UNSUPPORTED = "unsupported", "This kind of insight cannot be checked"
