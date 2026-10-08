"""Signal emitter for datadog `monitor_alerts` (record kind: issue).

The table holds one row per firing monitor alert event (`status:error`).
The warehouse source flattens JSON:API attributes to the row root, so the alert details sit in the nested `attributes` column.
The query JSON-extracts only identifiers and short labels.
It never selects `message`, the title, or any monitor message, query or notification text, because that free text can hold personal data.
"""

import hashlib
from typing import Any
from urllib.parse import urlparse

from structlog import get_logger

from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.datadog_common import clean_text
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

_ATTRS = "toString(attributes)"


def _raw_id(*path: str) -> str:
    # ClickHouse returns '' from JSONExtractString for a numeric value, and the monitor id is a number,
    # so the id is read raw and stripped of the quotes a string id would carry. A JSON null reads as 'null'.
    path_sql = ", ".join(f"'{part}'" for part in path)
    return f"nullIf(nullIf(replaceAll(JSONExtractRaw({_ATTRS}, {path_sql}), '\"', ''), ''), 'null')"


DATADOG_MONITOR_ALERT_FIELDS = (
    "id",
    "timestamp",
    f"coalesce({_raw_id('monitor_id')}, {_raw_id('monitor', 'id')}, '') AS monitor_id",
    (
        f"coalesce(nullIf(JSONExtractString({_ATTRS}, 'monitor', 'name'), ''), "
        f"nullIf(JSONExtractString({_ATTRS}, 'monitor', 'templated_name'), ''), '') AS monitor_name"
    ),
    f"JSONExtractString({_ATTRS}, 'monitor', 'transition', 'destination_state') AS destination_state",
    f"JSONExtractString({_ATTRS}, 'priority') AS priority",
    f"JSONExtractString({_ATTRS}, 'service') AS service",
    f"JSONExtractString({_ATTRS}, 'evt', 'type') AS monitor_kind",
    (
        f"coalesce(nullIf(JSONExtractString({_ATTRS}, 'monitor', 'alert_cycle_key_txt'), ''), "
        f"nullIf(JSONExtractString({_ATTRS}, 'monitor-alert-event', 'alert_cycle_key'), ''), '') AS alert_cycle_key"
    ),
    f"JSONExtractString({_ATTRS}, 'monitor', 'result', 'alert_url') AS alert_url",
)

_DATADOG_HOSTS = ("datadoghq.com", "datadoghq.eu", "ddog-gov.com")

# SignalEmissionRecord.source_id is limited to 200 characters.
_SOURCE_ID_MAX_LENGTH = 200


def datadog_url_or_none(value: Any) -> str | None:
    """The URL when it is an https link on a Datadog host, otherwise `None`."""
    url = clean_text(value)
    # A browser reads a backslash as a slash, but `urlparse` does not, so the two can disagree on the host.
    if not url or any(ch == "\\" or ch.isspace() or not ch.isprintable() for ch in url):
        return None
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme != "https" or not hostname:
        return None
    # The netloc must be only the host and an optional port, so userinfo cannot hide the real host.
    if parsed.netloc.lower() != (hostname if port is None else f"{hostname}:{port}"):
        return None
    if any(hostname == host or hostname.endswith(f".{host}") for host in _DATADOG_HOSTS):
        return url
    return None


def monitor_alert_source_id(record: dict[str, Any]) -> str:
    # Re-notifications inside one alert cycle share an id. A recovery followed by a new alert starts a new cycle.
    monitor_id = clean_text(record.get("monitor_id"))
    cycle = clean_text(record.get("alert_cycle_key")) or clean_text(record.get("id"))
    source_id = f"monitor_alert:{monitor_id}:{cycle}"
    if len(source_id) >= _SOURCE_ID_MAX_LENGTH:
        source_id = f"monitor_alert:{monitor_id}:{hashlib.sha256(cycle.encode('utf-8')).hexdigest()}"
    return source_id


def datadog_monitor_alert_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        event_id = clean_text(record["id"])
        monitor_id = clean_text(record["monitor_id"])
        monitor_name = clean_text(record["monitor_name"])
    except KeyError as e:
        msg = f"datadog monitor alert record missing required field {e}"
        logger.exception(msg, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not event_id or not monitor_id or not monitor_name:
        logger.info(
            "Ignoring datadog monitor alert with empty id, monitor id or monitor name",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    monitor_type = clean_text(record.get("monitor_kind"))
    priority = clean_text(record.get("priority"))
    service = clean_text(record.get("service"))
    details = [
        f"{label}: {value}"
        for label, value in (
            ("Monitor type", monitor_type.replace("_", " ")),
            ("Priority", f"P{priority}" if priority else ""),
            ("Service", service),
        )
        if value
    ]
    description = f"{monitor_name}\n{', '.join(details)}" if details else monitor_name
    return SignalEmitterOutput(
        source_product="datadog",
        source_type="issue",
        source_id=monitor_alert_source_id(record),
        description=description,
        weight=1.0,
        extra={
            "kind": "monitor_alert",
            "monitor_id": monitor_id,
            "state": clean_text(record.get("destination_state")) or None,
            "priority": priority or None,
            "service": service or None,
            "monitor_type": monitor_type or None,
            "alert_url": datadog_url_or_none(record.get("alert_url")),
        },
    )


DATADOG_MONITOR_ALERTS_CONFIG = SignalSourceTableConfig(
    source_product="datadog",
    source_type="issue",
    emitter=datadog_monitor_alert_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    # Re-notifications of one alert cycle are separate rows with a new timestamp and the same source id.
    # This flag makes the emit idempotency key the source id, so Temporal refuses a second signal for it.
    # The fetcher never reads the ledger rows, so a re-notification of a filtered alert is judged again.
    record_processed_outputs=True,
    partition_field="timestamp",
    partition_field_is_datetime_string=True,
    fields=DATADOG_MONITOR_ALERT_FIELDS,
    # The sync already asks Datadog for `status:error`. This guard keeps a recovery event from
    # becoming a signal if Datadog ever ignores that query term.
    where_clause=f"JSONExtractString({_ATTRS}, 'status') = 'error'",
    # Newest first, so the `max_records` limit drops the oldest re-notifications of a storm.
    order_by="timestamp DESC",
    max_records=1000,
    first_sync_lookback_days=1,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
