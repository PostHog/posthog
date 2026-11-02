"""Enumerations the product_analytics models and facade contracts use.

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


class InsightDataCheckMethod(LabeledStrEnum):
    COUNTED = "counted", "Counted every event on the days checked"
    SAMPLED = "sampled", "Checked a sample of the events on the days checked"


class InsightDataCheckSkipReason(LabeledStrEnum):
    TOO_MANY_EVENTS = "too_many_events", "The days checked hold too many events to count"
    READ_LIMIT = "read_limit", "The check would read more data than it is allowed"
    TIME_LIMIT = "time_limit", "The check took longer than it is allowed"
    MEMORY_LIMIT = "memory_limit", "The check needed more memory than it is allowed"
    TOO_FEW_SAMPLED_EVENTS = "too_few_sampled_events", "The sample has too few events to give a share"
    FILTERED_BY_TRAFFIC_TYPE = "filtered_by_traffic_type", "The insight already filters on traffic type"
    HIDDEN_PROPERTY = "hidden_property", "A property the check reads is hidden from you"
    INVALID_FILTER = "invalid_filter", "The project's internal and test users filter cannot run"
    ON_REQUEST = "on_request", "The check would read a lot of data, so it runs only on request"


class InsightDataCheckAction(LabeledStrEnum):
    FILTER_INTERNAL_USERS = "filter_internal_users", "Turn on the internal and test users filter for the insight"
    OPEN_FILTER_SETTINGS = "open_filter_settings", "Change the project's internal and test users filter"


class InsightDataChecksDepth(LabeledStrEnum):
    QUICK = "quick", "Read within a small budget, so the checks can run on every load"
    FULL = "full", "Read with the same limits as the insight's own query"


class InsightDataChecksStatus(LabeledStrEnum):
    PASSED = "passed", "No data issues found"
    WARNING = "warning", "A check found a small issue"
    PROBLEM = "problem", "A check found a large issue"
    PARTIAL = "partial", "Some checks could not run, and the others found no issue"
    ON_REQUEST = "on_request", "The checks would read a lot of data, so they run only on request"
    NO_EVENTS = "no_events", "No events to check"
    UNSUPPORTED = "unsupported", "This kind of insight cannot be checked"
    INCONCLUSIVE = "inconclusive", "No check could run"
