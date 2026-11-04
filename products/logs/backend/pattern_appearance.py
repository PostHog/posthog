"""New log patterns, as appearance alerts on the alerts platform.

Logs feeds the platform's registry with every pattern the pattern rollup holds, and the registry
decides which ones are new. A pattern's identity is its masker version, service, severity and masked
text, so a known pattern at a new severity is a new identity.
"""

import json
import hashlib
import datetime as dt
from typing import Any, Final

from posthog.utils import absolute_uri

from products.alerts_platform.backend.facade.appearance import appearance_source_config
from products.alerts_platform.backend.facade.contracts import (
    APPEARANCE_DETAIL_KEY,
    AnnouncedTransition,
    MessageDetail,
    MessageLink,
    OccurrenceFeed,
    OccurrenceKind,
    SeenIdentity,
    SourceConfigSpec,
    SourceDescription,
)
from products.logs.backend.logs_url_params import build_logs_url_params

SEED_LOOKBACK: Final = dt.timedelta(days=14)
# The rollup's grid. A sighting is dated at the end of its bucket, the earliest time it is known to have
# happened by, so an alert created inside a bucket still announces a pattern first logged later in it.
BUCKET: Final = dt.timedelta(minutes=5)
# A link opens the logs from this long before the first sighting, so the first lines are in view.
LINK_LEAD: Final = dt.timedelta(minutes=10)
FILTER_KEYS: Final = ("service_name", "severity_text", "environment", "namespace", "pattern")
MAX_PATTERN_DETAIL: Final = 2000
ROLLOUT_FLAG: Final = "platform-alerts-source-logs-patterns"


def _ready_until(team_id: int, now: dt.datetime) -> dt.datetime:
    """The end of the newest bucket the volume rollup also treats as final, so late logs are already in it."""
    # Imported here, because this module loads in `ready()` and the Temporal layer must stay off that path.
    from products.logs.backend.temporal.volume_tick.activities import due_bucket_bounds  # noqa: PLC0415

    return due_bucket_bounds(now).end


def _seen(team_id: int, since: dt.datetime, until: dt.datetime, limit: int) -> list[SeenIdentity]:
    # Imported here, because this module loads in `ready()` and the query layer must stay off that path.
    from products.logs.backend.pattern_appearance_query import first_sightings  # noqa: PLC0415

    # The registry's bounds are sighting times, which are bucket ends, so the buckets they cover start one bucket earlier.
    return [_identity(*row) for row in first_sightings(team_id, since - BUCKET, until - BUCKET, limit)]


def _identity(
    service: str,
    severity: str,
    version: int,
    pattern: str,
    environment: str,
    namespace: str,
    first_bucket: dt.datetime,
    last_bucket: dt.datetime,
) -> SeenIdentity:
    digest = hashlib.sha256(json.dumps([version, service, severity, pattern]).encode()).hexdigest()[:32]
    return SeenIdentity(
        identity_key=f"pattern:{digest}",
        seen_at=_utc(first_bucket) + BUCKET,
        last_seen_at=_utc(last_bucket) + BUCKET,
        labels={
            "service_name": service,
            "severity_text": severity,
            "environment": environment,
            "namespace": namespace,
            "pattern": pattern,
        },
        detail={"pattern": _clipped(pattern), "pattern_version": version},
    )


def _clipped(pattern: str) -> str:
    """The pattern cut to `MAX_PATTERN_DETAIL` bytes, so wide characters cannot push the detail over its budget."""
    return pattern.encode()[:MAX_PATTERN_DETAIL].decode(errors="ignore")


def _utc(moment: dt.datetime) -> dt.datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)


LOGS_PATTERN_FEED: Final = OccurrenceFeed(ready_until=_ready_until, seen=_seen, seed_lookback=SEED_LOOKBACK)


def load_logs_pattern_source_config() -> SourceConfigSpec:
    return appearance_source_config(name="LogsPatternAppearance", filter_keys=FILTER_KEYS, rollout_flag=ROLLOUT_FLAG)


def describe_logs_pattern(*, project_id: int, transition: AnnouncedTransition) -> SourceDescription:
    labels = transition.labels
    service = labels.get("service_name") or "an unnamed service"
    back = transition.source_detail.get(APPEARANCE_DETAIL_KEY) == OccurrenceKind.REAPPEARED.value
    details = [
        MessageDetail(label="Pattern", value=str(transition.source_detail.get("pattern") or labels.get("pattern", ""))),
        MessageDetail(label="Severity", value=labels.get("severity_text", "")),
    ]
    if labels.get("environment"):
        details.append(MessageDetail(label="Environment", value=labels["environment"]))
    if first_seen := transition.source_detail.get("first_seen_at"):
        details.append(MessageDetail(label="First seen", value=str(first_seen)))
    return SourceDescription(
        headline=f"{'Resolved log pattern is back' if back else 'New log pattern'} in {service}",
        details=tuple(details),
        data_link=MessageLink(label="View logs", url=_logs_url(project_id, labels, transition.source_detail)),
    )


def _logs_url(project_id: int, labels: dict[str, str], detail: dict[str, Any]) -> str:
    """The announced pattern's logs, from just before its first sighting."""
    filters: dict[str, Any] = {
        "serviceNames": [labels["service_name"]] if labels.get("service_name") else [],
        "severityLevels": [labels["severity_text"]] if labels.get("severity_text") else [],
    }
    pattern = detail.get("pattern")
    # A pattern cut to fit the detail would match nothing, so the link then filters by service and severity only.
    if isinstance(pattern, str) and len(pattern.encode()) < MAX_PATTERN_DETAIL and detail.get("pattern_version"):
        filters["filterGroup"] = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {"key": "pattern", "value": [pattern], "operator": "exact", "type": "log"},
                        {
                            "key": "pattern_version",
                            "value": detail["pattern_version"],
                            "operator": "exact",
                            "type": "log",
                        },
                    ],
                }
            ],
        }
    first_seen = detail.get("first_seen_at")
    date_from = dt.datetime.fromisoformat(first_seen) - LINK_LEAD if isinstance(first_seen, str) else None
    params = build_logs_url_params(filters, date_from=date_from)
    # The query goes on after `absolute_uri`, which refuses a URL that holds an encoded backslash.
    return absolute_uri(f"/project/{project_id}/logs") + (f"?{params}" if params else "")
