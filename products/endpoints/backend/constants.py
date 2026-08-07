import enum
import dataclasses


class MaterializationFixStatus(enum.StrEnum):
    """Outcome of an AI materialization-fix suggestion run."""

    OK = "ok"
    CANNOT_FIX = "cannot_fix"
    INVALID = "invalid"
    MODEL_ERROR = "model_error"


@dataclasses.dataclass(frozen=True)
class DataFreshnessBucket:
    seconds: int
    sync_label: str  # key understood by sync_frequency_to_sync_frequency_interval
    human: str


DATA_FRESHNESS_BUCKET_SPECS: tuple[DataFreshnessBucket, ...] = (
    DataFreshnessBucket(900, "15min", "15 minutes"),
    DataFreshnessBucket(1800, "30min", "30 minutes"),
    DataFreshnessBucket(3600, "1hour", "1 hour"),
    DataFreshnessBucket(21600, "6hour", "6 hours"),
    DataFreshnessBucket(43200, "12hour", "12 hours"),
    DataFreshnessBucket(86400, "24hour", "24 hours"),
    DataFreshnessBucket(604800, "7day", "7 days"),
)

DATA_FRESHNESS_BUCKETS: dict[int, str] = {b.seconds: b.sync_label for b in DATA_FRESHNESS_BUCKET_SPECS}
VALID_DATA_FRESHNESS_SECONDS: frozenset[int] = frozenset(DATA_FRESHNESS_BUCKETS)
DEFAULT_DATA_FRESHNESS_SECONDS = 86400

ENDPOINT_NAME_REGEX = r"^[a-zA-Z][a-zA-Z0-9_-]{0,127}$"

# Matches the `log_source` column written for endpoint execution logs in the `log_entries`
# ClickHouse table. The Logs tab and the `endpoints_logs_retrieve` API both read by this value.
ENDPOINTS_LOG_SOURCE = "endpoints"
