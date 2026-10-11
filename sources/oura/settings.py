from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class OuraEndpointConfig:
    name: str
    # Path under the v2 base URL, e.g. "/usercollection/daily_sleep".
    path: str
    incremental_fields: list[IncrementalField]
    # Column whose max value the pipeline checkpoints and that we feed back as the next sync's
    # start filter. Must be the date/datetime field the API actually filters on (e.g. "day",
    # "start_day", or "timestamp"), so max(cursor) -> next start_(date|datetime) is correct.
    cursor_field: Optional[str] = None
    # Stable field to partition by (never an updated_at style field). Daily summaries are keyed by
    # an immutable record date, so we partition by that date.
    partition_key: Optional[str] = None
    # Filter style this endpoint supports. "date" -> start_date/end_date (record-date filtering on
    # most usercollection endpoints), "datetime" -> start_datetime/end_datetime (time-series), and
    # None -> no date filtering at all (single/static documents -> full refresh only).
    date_filter: Optional[str] = None
    # Some endpoints (personal_info) return a single flat document rather than a
    # `{data: [...], next_token}` collection envelope; the transport dispatches on this.
    is_single_document: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True


def _date_fields(*names: str) -> list[IncrementalField]:
    return [
        {
            "label": name,
            "type": IncrementalFieldType.Date,
            "field": name,
            "field_type": IncrementalFieldType.Date,
        }
        for name in names
    ]


def _datetime_fields(*names: str) -> list[IncrementalField]:
    return [
        {
            "label": name,
            "type": IncrementalFieldType.DateTime,
            "field": name,
            "field_type": IncrementalFieldType.DateTime,
        }
        for name in names
    ]


OURA_ENDPOINTS: dict[str, OuraEndpointConfig] = {
    "daily_activity": OuraEndpointConfig(
        name="daily_activity",
        path="/usercollection/daily_activity",
        cursor_field="day",
        partition_key="day",
        date_filter="date",
        incremental_fields=_date_fields("day"),
    ),
    "daily_readiness": OuraEndpointConfig(
        name="daily_readiness",
        path="/usercollection/daily_readiness",
        cursor_field="day",
        partition_key="day",
        date_filter="date",
        incremental_fields=_date_fields("day"),
    ),
    "daily_sleep": OuraEndpointConfig(
        name="daily_sleep",
        path="/usercollection/daily_sleep",
        cursor_field="day",
        partition_key="day",
        date_filter="date",
        incremental_fields=_date_fields("day"),
    ),
    "daily_spo2": OuraEndpointConfig(
        name="daily_spo2",
        path="/usercollection/daily_spo2",
        cursor_field="day",
        partition_key="day",
        date_filter="date",
        incremental_fields=_date_fields("day"),
    ),
    "daily_stress": OuraEndpointConfig(
        name="daily_stress",
        path="/usercollection/daily_stress",
        cursor_field="day",
        partition_key="day",
        date_filter="date",
        incremental_fields=_date_fields("day"),
    ),
    "daily_cardiovascular_age": OuraEndpointConfig(
        name="daily_cardiovascular_age",
        path="/usercollection/daily_cardiovascular_age",
        cursor_field="day",
        partition_key="day",
        date_filter="date",
        incremental_fields=_date_fields("day"),
    ),
    "daily_resilience": OuraEndpointConfig(
        name="daily_resilience",
        path="/usercollection/daily_resilience",
        cursor_field="day",
        partition_key="day",
        date_filter="date",
        incremental_fields=_date_fields("day"),
    ),
    "sleep": OuraEndpointConfig(
        name="sleep",
        path="/usercollection/sleep",
        cursor_field="day",
        partition_key="day",
        date_filter="date",
        incremental_fields=_date_fields("day"),
    ),
    "sleep_time": OuraEndpointConfig(
        name="sleep_time",
        path="/usercollection/sleep_time",
        cursor_field="day",
        partition_key="day",
        date_filter="date",
        incremental_fields=_date_fields("day"),
    ),
    "session": OuraEndpointConfig(
        name="session",
        path="/usercollection/session",
        cursor_field="day",
        partition_key="day",
        date_filter="date",
        incremental_fields=_date_fields("day"),
    ),
    "workout": OuraEndpointConfig(
        name="workout",
        path="/usercollection/workout",
        cursor_field="day",
        partition_key="day",
        date_filter="date",
        incremental_fields=_date_fields("day"),
    ),
    "tag": OuraEndpointConfig(
        name="tag",
        path="/usercollection/tag",
        cursor_field="day",
        partition_key="day",
        date_filter="date",
        incremental_fields=_date_fields("day"),
    ),
    "enhanced_tag": OuraEndpointConfig(
        name="enhanced_tag",
        path="/usercollection/enhanced_tag",
        cursor_field="start_day",
        partition_key="start_day",
        date_filter="date",
        incremental_fields=_date_fields("start_day"),
    ),
    "rest_mode_period": OuraEndpointConfig(
        name="rest_mode_period",
        path="/usercollection/rest_mode_period",
        cursor_field="start_day",
        partition_key="start_day",
        date_filter="date",
        incremental_fields=_date_fields("start_day"),
    ),
    "vO2_max": OuraEndpointConfig(
        name="vO2_max",
        path="/usercollection/vO2_max",
        cursor_field="day",
        partition_key="day",
        date_filter="date",
        incremental_fields=_date_fields("day"),
    ),
    # Time-series heart-rate samples. Filtered by start_datetime/end_datetime, not start_date/end_date,
    # and the response carries no `id` — a sample is identified by its timestamp and source.
    "heartrate": OuraEndpointConfig(
        name="heartrate",
        path="/usercollection/heartrate",
        cursor_field="timestamp",
        partition_key="timestamp",
        date_filter="datetime",
        incremental_fields=_datetime_fields("timestamp"),
        primary_keys=["timestamp", "source"],
    ),
    # Single, mostly-static document for the authenticated user. No date filtering -> full refresh.
    "personal_info": OuraEndpointConfig(
        name="personal_info",
        path="/usercollection/personal_info",
        date_filter=None,
        is_single_document=True,
        incremental_fields=[],
    ),
    # Ring hardware/configuration records. No date filtering -> full refresh.
    "ring_configuration": OuraEndpointConfig(
        name="ring_configuration",
        path="/usercollection/ring_configuration",
        date_filter=None,
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(OURA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OURA_ENDPOINTS.items()
}
