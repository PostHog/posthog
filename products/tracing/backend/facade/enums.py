"""
Exported enums and constants for tracing.

Small products can keep enums in contracts.py instead. Split
into this file when contracts.py gets crowded.

Rule: if an enum appears in a contract dataclass field, it
belongs here (or in contracts.py). Shared types that other
products need to interpret contract objects also belong here.

Internal-only constants (DB magic values, feature flags, etc.)
should stay in the implementation (logic.py, models.py).
"""

from posthog.enums import LabeledStrEnum


class ServiceHealthCompare(LabeledStrEnum):
    NONE = "none"
    PREVIOUS_PERIOD = "previous_period"
    PREVIOUS_DAY = "previous_day"
    PREVIOUS_WEEK = "previous_week"
    CUSTOM = "custom"


class ServiceHealthBaseline(LabeledStrEnum):
    NONE = "none"
    PREVIOUS_PERIOD = "previous_period"
    PREVIOUS_DAY = "previous_day"
    PREVIOUS_WEEK = "previous_week"


class ServiceHealthSpanScope(LabeledStrEnum):
    ENTRY = "entry"
    ALL = "all"


class ServiceHealthOrderBy(LabeledStrEnum):
    STATUS = "status"
    ERROR_RATE = "error_rate"
    P95 = "p95"
    THROUGHPUT = "throughput"
    ERROR_COUNT = "error_count"


class ServiceHealthStatus(LabeledStrEnum):
    SILENT = "silent"
    REGRESSED = "regressed"
    DEGRADED = "degraded"
    NEW = "new"
    RECOVERED = "recovered"
    IMPROVED = "improved"
    OK = "ok"
