"""Signal emitter for betterstack `incidents` (record kind: incident).

`name` is the monitor or heartbeat name and `cause` says what failed (status code, timeout, missed heartbeat).
The table has no creation column, so `started_at` (an ISO string) is the partition field.
`url` is the monitored URL, not an incident permalink, so its credentials and query string are dropped.
"""

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

BETTERSTACK_FIELDS = (
    "id",
    "name",
    "cause",
    "url",
    "started_at",
)

_flat_emitter = make_flat_emitter(
    source_product="betterstack",
    source_type="incident",
    id_field="id",
    title_field="name",
    body_field="cause",
    extra_fields=("url", "started_at"),
)


def redact_monitored_url(url: Any) -> str | None:
    """Keep the scheme, host, port and path of a monitored URL; drop userinfo, query and fragment."""
    if not url:
        return None
    try:
        parts = urlsplit(str(url))
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        if parts.port is not None:
            host = f"{host}:{parts.port}"
    except ValueError:
        return None
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def betterstack_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    output = _flat_emitter(team_id, record)
    if output is not None:
        output.extra["url"] = redact_monitored_url(output.extra.get("url"))
    return output


BETTERSTACK_CONFIG = SignalSourceTableConfig(
    source_product="betterstack",
    source_type="incident",
    emitter=betterstack_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="started_at",
    partition_field_is_datetime_string=True,
    fields=BETTERSTACK_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
