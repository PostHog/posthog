from dataclasses import field
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

# ``daily_window`` sends one request per UTC day (``from``/``to``) and stamps that day onto each row.
# The Metrics API breakdowns aggregate over the whole requested window, so this turns them into a
# daily fact table.
PaginationStyle = Literal["cursor", "none", "daily_window"]


@frozen
class SparkPostEndpointConfig:
    name: str
    path: str
    # Key in the response body holding the list of records. SparkPost wraps every list endpoint in
    # ``{"results": [...]}``.
    data_path: str = "results"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    pagination: PaginationStyle = "none"
    per_page: int = 10000
    # Stable, immutable datetime field used for partitioning (never ``updated``/``last_update_time``).
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Server-side timestamp filter param (e.g. ``from``). Only set when the API genuinely filters
    # server-side — leaving it ``None`` keeps the endpoint full-refresh only.
    timestamp_filter_param: Optional[str] = None
    # First-sync lookback window for endpoints with a server-side timestamp filter. SparkPost only
    # retains message events for 10 days, so a "full" backfill of events is bounded to that window.
    default_lookback_days: Optional[int] = None
    should_sync_default: bool = True
    extra_params: dict[str, str] = field(default_factory=dict)

    @property
    def supports_incremental(self) -> bool:
        return self.timestamp_filter_param is not None

    @property
    def is_metrics(self) -> bool:
        return self.path.startswith("/api/v1/metrics/")

    @property
    def supports_append(self) -> bool:
        # Metrics rows are totals that change until their day or bucket ends, and each run fetches the
        # watermark again. Append mode would keep the partial and the final totals side by side.
        return self.supports_incremental and not self.is_metrics


def _timestamp_incremental_fields(
    field_name: str, field_type: IncrementalFieldType = IncrementalFieldType.DateTime
) -> list[IncrementalField]:
    return [
        {
            "label": field_name,
            "type": field_type,
            "field": field_name,
            "field_type": field_type,
        }
    ]


# Metrics API data is retained for 6 months.
METRICS_LOOKBACK_DAYS = 180
METRICS_LIMIT = "10000"
DAILY_WINDOW_FIELD = "date"

# The metrics each endpoint accepts, less the Deliverability Add-On metrics (seed and panel counts),
# which only accounts with that add-on can request.
_CORE_METRICS = [
    "count_targeted",
    "count_injected",
    "count_sent",
    "count_accepted",
    "count_delivered",
    "count_delivered_first",
    "count_delivered_subsequent",
    "count_bounce",
    "count_inband_bounce",
    "count_outofband_bounce",
    "count_soft_bounce",
    "count_hard_bounce",
    "count_block_bounce",
    "count_admin_bounce",
    "count_undetermined_bounce",
    "count_rejected",
    "count_policy_rejection",
    "count_generation_rejection",
    "count_generation_failed",
    "count_delayed",
    "count_delayed_first",
    "count_rendered",
    "count_nonprefetched_rendered",
    "count_unique_rendered",
    "count_nonprefetched_unique_rendered",
    "count_unique_confirmed_opened",
    "count_nonprefetched_unique_confirmed_opened",
    "count_clicked",
    "count_unique_clicked",
    "count_spam_complaint",
    "total_delivery_time_first",
    "total_delivery_time_subsequent",
    "total_msg_volume",
]
TIME_SERIES_METRICS = [
    *_CORE_METRICS,
    "count_initial_rendered",
    "count_nonprefetched_initial_rendered",
    "count_unique_initial_rendered",
    "count_nonprefetched_unique_initial_rendered",
]
BOUNCE_METRICS = ["count_bounce", "count_inband_bounce", "count_outofband_bounce", "count_admin_bounce"]


def _daily_metrics_endpoint(
    name: str, path: str, primary_keys: list[str], metrics: Optional[list[str]] = None
) -> SparkPostEndpointConfig:
    extra_params = {"limit": METRICS_LIMIT}
    if metrics:
        extra_params["metrics"] = ",".join(metrics)
    return SparkPostEndpointConfig(
        name=name,
        path=path,
        primary_keys=[DAILY_WINDOW_FIELD, *primary_keys],
        pagination="daily_window",
        partition_key=DAILY_WINDOW_FIELD,
        incremental_fields=_timestamp_incremental_fields(DAILY_WINDOW_FIELD, IncrementalFieldType.Date),
        default_incremental_field=DAILY_WINDOW_FIELD,
        timestamp_filter_param="from",
        default_lookback_days=METRICS_LOOKBACK_DAYS,
        extra_params=extra_params,
    )


# Endpoint catalog. SparkPost (now part of Bird) ships no dedicated Airbyte/Fivetran connector, so
# coverage is drawn from the public SparkPost API: the Events Search API plus the management list
# endpoints a user typically wants in the warehouse (suppression list, recipient lists, templates,
# sending domains, subaccounts, webhooks).
#
# Incremental vs full refresh: the Events Search API and the Metrics API expose a genuine server-side
# timestamp filter (``from``/``to``), so those endpoints are incremental. The management list
# endpoints have no server-side time filter, so they ship as full refresh and dedupe on their
# primary key.
SPARKPOST_ENDPOINTS: dict[str, SparkPostEndpointConfig] = {
    # --- Append-only, server-side timestamp filter (incremental) ---
    "events": SparkPostEndpointConfig(
        name="events",
        path="/api/v1/events/message",
        primary_keys=["event_id"],
        pagination="cursor",
        per_page=10000,
        partition_key="timestamp",
        incremental_fields=_timestamp_incremental_fields("timestamp"),
        default_incremental_field="timestamp",
        timestamp_filter_param="from",
        default_lookback_days=10,
    ),
    # --- Full refresh ---
    "suppression_list": SparkPostEndpointConfig(
        name="suppression_list",
        path="/api/v1/suppression-list",
        # A recipient can be suppressed independently for transactional and non-transactional mail,
        # surfacing as two rows that share a ``recipient`` — so the type is part of the key.
        primary_keys=["recipient", "type"],
        pagination="cursor",
        per_page=10000,
        partition_key="created",
    ),
    "recipient_lists": SparkPostEndpointConfig(
        name="recipient_lists",
        path="/api/v1/recipient-lists",
        primary_keys=["id"],
        pagination="none",
    ),
    "templates": SparkPostEndpointConfig(
        name="templates",
        path="/api/v1/templates",
        primary_keys=["id"],
        pagination="none",
    ),
    "sending_domains": SparkPostEndpointConfig(
        name="sending_domains",
        path="/api/v1/sending-domains",
        primary_keys=["domain"],
        pagination="none",
    ),
    "subaccounts": SparkPostEndpointConfig(
        name="subaccounts",
        path="/api/v1/subaccounts",
        primary_keys=["id"],
        pagination="none",
    ),
    "webhooks": SparkPostEndpointConfig(
        name="webhooks",
        path="/api/v1/webhooks",
        primary_keys=["id"],
        pagination="none",
    ),
    # --- Metrics API (aggregates, incremental on a server-side ``from`` filter) ---
    "deliverability_time_series": SparkPostEndpointConfig(
        name="deliverability_time_series",
        path="/api/v1/metrics/deliverability/time-series",
        primary_keys=["ts"],
        pagination="none",
        partition_key="ts",
        incremental_fields=_timestamp_incremental_fields("ts"),
        default_incremental_field="ts",
        timestamp_filter_param="from",
        default_lookback_days=METRICS_LOOKBACK_DAYS,
        # ``day`` buckets are always UTC and have no maximum time window.
        extra_params={"precision": "day", "metrics": ",".join(TIME_SERIES_METRICS)},
    ),
    "deliverability_by_template": _daily_metrics_endpoint(
        "deliverability_by_template",
        "/api/v1/metrics/deliverability/template",
        ["template_id"],
        _CORE_METRICS,
    ),
    # One bounce reason can carry several bounce classifications, so the classification is keyed too.
    "bounce_reasons": _daily_metrics_endpoint(
        "bounce_reasons",
        "/api/v1/metrics/deliverability/bounce-reason",
        ["reason", "classification_id"],
        BOUNCE_METRICS,
    ),
    "bounce_reasons_by_domain": _daily_metrics_endpoint(
        "bounce_reasons_by_domain",
        "/api/v1/metrics/deliverability/bounce-reason/domain",
        ["reason", "domain", "classification_id"],
        BOUNCE_METRICS,
    ),
    "rejection_reasons": _daily_metrics_endpoint(
        "rejection_reasons",
        "/api/v1/metrics/deliverability/rejection-reason",
        ["reason", "rejection_category_id"],
    ),
    "rejection_reasons_by_domain": _daily_metrics_endpoint(
        "rejection_reasons_by_domain",
        "/api/v1/metrics/deliverability/rejection-reason/domain",
        ["reason", "domain", "rejection_category_id"],
    ),
    "delay_reasons": _daily_metrics_endpoint(
        "delay_reasons",
        "/api/v1/metrics/deliverability/delay-reason",
        ["reason"],
    ),
    "delay_reasons_by_domain": _daily_metrics_endpoint(
        "delay_reasons_by_domain",
        "/api/v1/metrics/deliverability/delay-reason/domain",
        ["reason", "domain"],
    ),
}

ENDPOINTS = tuple(SPARKPOST_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SPARKPOST_ENDPOINTS.items()
}

# SparkPost retains message events for only 10 days, so the first sync of ``events`` can reach back
# at most that far.
LIMITED_RETENTION_ENDPOINTS = {"events"}

# The Metrics API retains data for 6 months, which bounds the first sync of the metrics tables.
METRICS_ENDPOINTS = {name for name, config in SPARKPOST_ENDPOINTS.items() if config.is_metrics}

# --- Event webhooks ---------------------------------------------------------------------------
#
# Only ``events`` can be fed by webhooks. It is the append-only message-event stream, keyed on an
# immutable ``event_id``, and it is the only endpoint SparkPost pushes at all — the management
# lists (templates, sending domains, suppression list, ...) have no webhook events. Push delivery
# also outlives the 10-day retention window the poll path is bounded by, so events pushed today
# stay in the warehouse long after SparkPost stops returning them.
WEBHOOK_SCHEMA_NAMES = {"events"}

# Every element of a SparkPost delivery is ``{"msys": {"<grouping>": {...}}}``. We only subscribe
# to message-event types, so the only grouping we ever see is ``message_event``.
WEBHOOK_EVENT_GROUPING = "message_event"

# Our schema name -> the grouping the Hog template routes on.
WEBHOOK_RESOURCE_MAP = {"events": WEBHOOK_EVENT_GROUPING}

# The event types the webhook subscribes to. Deliberately the same set the Events Search API
# (``/api/v1/events/message``) returns, so a pushed row and a polled row are the same object with
# the same field names and merge cleanly on ``event_id``. Relay events (``relay_*``) and the A/B
# test events are excluded on purpose: they are separate groupings the Events Search API does not
# return, so they would land differently-shaped rows in the same table.
WEBHOOK_EVENT_TYPES = [
    "amp_click",
    "amp_initial_open",
    "amp_open",
    "bounce",
    "click",
    "delay",
    "delivery",
    "generation_failure",
    "generation_rejection",
    "initial_open",
    "injection",
    "link_unsubscribe",
    "list_unsubscribe",
    "open",
    "out_of_band",
    "policy_rejection",
    "spam_complaint",
]

# Name given to the webhook we register, so it is recognisable in the SparkPost UI.
WEBHOOK_NAME = "PostHog data warehouse"

# SparkPost POSTs a *batch* of events per delivery, but a Hog function may only produce one
# payload per request. The template therefore hands the whole batch over as a JSON string under
# this key and the source's table transformer explodes it into one row per event.
WEBHOOK_BATCH_KEY = "sparkpost_webhook_batch"
