"""Exported enums for warehouse_suggestions."""

from posthog.enums import LabeledStrEnum


class WarehouseSuggestionKind(LabeledStrEnum):
    CERTIFY = "certify"
    DEPRECATE = "deprecate"
    MATERIALIZE = "materialize"


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
