"""Materialize event properties that budget-burning scanners filter on.

A scanner filtering on an unmaterialized event property (most often a `$feature/...` key served
from the property-groups Map column) can read hundreds of GB per query where a materialized column
reads a fraction of one. The sweep throttle only stretches how often that happens; this closes the
loop by feeding the specific keys to the same `materialize_properties_task` machinery the weekly
analyzer cron runs, once a scanner's metered spend shows the cost is real and sustained.
"""

import re
import datetime as dt

from django.core.exceptions import ValidationError as DjangoValidationError

from pydantic import ValidationError
from temporalio import activity

from posthog.schema import EventPropertyFilter, FeaturePropertyFilter

from posthog.dataclasses import frozen
from posthog.settings import EE_AVAILABLE
from posthog.settings.utils import get_from_env, str_to_bool

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.metrics import record_auto_materialize_outcome
from products.replay_vision.backend.temporal.read_meter_types import AutoMaterializeResult, sweep_spend_bytes_24h

if EE_AVAILABLE:
    from ee.clickhouse.materialized_columns.analyze import materialize_properties_task
    from ee.clickhouse.materialized_columns.columns import get_materialized_columns

# Off by default: enabling column creation is a deliberate per-environment decision. While off, the
# activity still logs and counts every candidate, which is the dry run to watch before flipping it.
AUTO_MATERIALIZE_ENABLED = get_from_env("REPLAY_VISION_AUTO_MATERIALIZE_ENABLED", False, type_cast=str_to_bool)
# Metered daily reads (sweep + deep passes; backfill excluded, so a one-day backfill spike cannot
# qualify a scanner). Five times the sweep budget: only scanners the throttle cannot make cheap get here.
AUTO_MATERIALIZE_MIN_DAILY_READ_BYTES = get_from_env(
    "REPLAY_VISION_AUTO_MATERIALIZE_MIN_DAILY_READ_BYTES", 1024**4, type_cast=int
)
# Days of history to backfill into a new column; 0 relies on inserts, which covers the sweep's
# short lookback within days. Matches the weekly analyzer cron's default.
AUTO_MATERIALIZE_BACKFILL_DAYS = get_from_env("REPLAY_VISION_AUTO_MATERIALIZE_BACKFILL_DAYS", 0, type_cast=int)
# Ceiling on new columns per acting run; with one acting run per day this caps cluster-wide growth.
AUTO_MATERIALIZE_MAX_PER_RUN = 2
# The read meter runs hourly; only this UTC hour's run may create columns, making the cap daily.
_ACTING_HOUR_UTC = 3

# Property filter types that read event properties; everything else (person, session, log_entry,
# hogql, cohort) does not touch the events properties column and cannot be helped by this.
_EVENT_SCOPED_FILTER_TYPES = ("event", "feature")

# Mirrors the weekly analyzer's extraction charset. Materialized-column metadata round-trips the key
# through a `::`-delimited column comment, so a key like `foo::bar` would poison every registry
# lookup cluster-wide; scanner filters are user input, so only plainly safe keys become columns.
_SAFE_PROPERTY_KEY = re.compile(r"^[a-zA-Z0-9_\-\.\$\/ ]{1,200}$")


@frozen
class _Candidate:
    property_name: str
    scanner_id: str
    spend_bytes_24h: int


@activity.defn
@track_activity()
def auto_materialize_scanner_properties_activity() -> AutoMaterializeResult:
    now = dt.datetime.now(dt.UTC)
    candidates = _candidate_properties(now)
    for candidate in candidates:
        activity.logger.info(
            "replay_vision.auto_materialize_candidate",
            extra={
                "property_name": candidate.property_name,
                "scanner_id": candidate.scanner_id,
                "spend_bytes_24h": candidate.spend_bytes_24h,
            },
        )
    if not candidates:
        return AutoMaterializeResult()
    if not AUTO_MATERIALIZE_ENABLED or not EE_AVAILABLE:
        record_auto_materialize_outcome("candidate_logged", len(candidates))
        return AutoMaterializeResult(candidates=len(candidates))
    if now.hour != _ACTING_HOUR_UTC:
        record_auto_materialize_outcome("deferred_to_acting_hour", len(candidates))
        return AutoMaterializeResult(candidates=len(candidates))

    acted = candidates[:AUTO_MATERIALIZE_MAX_PER_RUN]
    materialize_properties_task(
        properties_to_materialize=[("events", "properties", c.property_name) for c in acted],
        maximum=AUTO_MATERIALIZE_MAX_PER_RUN,
        backfill_period_days=AUTO_MATERIALIZE_BACKFILL_DAYS,
    )
    record_auto_materialize_outcome("materialized", len(acted))
    activity.logger.info(
        "replay_vision.auto_materialized_properties",
        extra={"property_names": [c.property_name for c in acted]},
    )
    return AutoMaterializeResult(candidates=len(candidates), materialized=len(acted))


def _candidate_properties(now: dt.datetime) -> list[_Candidate]:
    """Unmaterialized event properties filtered on by scanners over the spend threshold, costliest first."""
    scanners = ReplayScanner.objects.filter(enabled=True).only(
        "id", "query", "fast_read_bytes_by_hour", "deep_read_bytes_by_hour"
    )
    qualifying = [
        (scanner, spend)
        for scanner in scanners
        if (spend := _daily_read_bytes(scanner, now)) >= AUTO_MATERIALIZE_MIN_DAILY_READ_BYTES
    ]
    if not qualifying:
        return []

    already_materialized = _materialized_event_properties()
    best_per_property: dict[str, _Candidate] = {}
    for scanner, spend in sorted(qualifying, key=lambda pair: pair[1], reverse=True):
        for key in sorted(_event_property_keys(scanner)):
            if key in already_materialized or key in best_per_property:
                continue
            best_per_property[key] = _Candidate(property_name=key, scanner_id=str(scanner.id), spend_bytes_24h=spend)
    # Name breaks spend ties, so which candidates fit under the per-run cap is deterministic.
    return sorted(best_per_property.values(), key=lambda c: (-c.spend_bytes_24h, c.property_name))


def _daily_read_bytes(scanner: ReplayScanner, now: dt.datetime) -> int:
    """Trailing-24h reads from the scanner's own passes, so backfill spend cannot qualify it.

    Rows the meter has not split yet read as zero rather than falling back to the total, which
    carries backfill reads; missing a transitional hour of candidates costs nothing.
    """
    return sweep_spend_bytes_24h(scanner.fast_read_bytes_by_hour, now) + sweep_spend_bytes_24h(
        scanner.deep_read_bytes_by_hour, now
    )


def _materialized_event_properties() -> set[str]:
    if not EE_AVAILABLE:
        return set()
    return {prop for prop, table_column in get_materialized_columns("events") if table_column == "properties"}


def _event_property_keys(scanner: ReplayScanner) -> set[str]:
    try:
        query = scanner.recordings_query()
    except (ValidationError, DjangoValidationError):
        return set()
    keys = {
        prop.key for prop in (query.properties or []) if isinstance(prop, EventPropertyFilter | FeaturePropertyFilter)
    }
    for entity in [*(query.events or []), *(query.actions or [])]:
        for prop in entity.get("properties") or []:
            if (
                isinstance(prop, dict)
                and prop.get("type") in _EVENT_SCOPED_FILTER_TYPES
                and isinstance(prop.get("key"), str)
            ):
                keys.add(prop["key"])
    return {key for key in keys if _SAFE_PROPERTY_KEY.match(key)}
