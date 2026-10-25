"""Exported enums for warehouse_suggestions."""

from posthog.enums import LabeledStrEnum


class WarehouseSuggestionKind(LabeledStrEnum):
    CERTIFY = "certify"
    DEPRECATE = "deprecate"
    MATERIALIZE = "materialize"
    SQL_REPAIR = ("sql_repair", "SQL repair")
    UNMATERIALIZE = "unmaterialize"


def warehouse_suggestion_kind_choices() -> list[tuple[str, str]]:
    return WarehouseSuggestionKind.choices


class WarehouseSuggestionStatus(LabeledStrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    EXPIRED = "expired"
    AUTO_RESOLVED = ("auto_resolved", "Auto-resolved")


class WarehouseSuggestionSubjectKind(LabeledStrEnum):
    SAVED_QUERY = ("saved_query", "Saved query")
    TABLE = "table"


class WarehouseSuggestionDismissalReason(LabeledStrEnum):
    NOT_USEFUL = ("not_useful", "Not useful")
    NOT_NOW = ("not_now", "Not now")
    OTHER = "other"


class WarehouseSuggestionAssetOutcome(LabeledStrEnum):
    LIVE = "live"
    DELETED = "deleted"
    UNUSED = "unused"


class WarehouseSuggestionRefreshMode(LabeledStrEnum):
    FULL = "full"
    INCREMENTAL = "incremental"


class WarehouseSuggestionRefreshIntervalBasis(LabeledStrEnum):
    SOURCE_SYNC = ("source_sync", "Source sync")
    FASTEST_SCHEDULE = ("fastest_schedule", "Fastest schedule")
    READ_RATE = ("read_rate", "Read rate")
    SAVINGS = "savings"
