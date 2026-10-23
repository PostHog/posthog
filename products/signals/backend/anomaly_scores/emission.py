"""Turn scored buckets into `$anomaly_score` events in the project's own events."""

import json
import uuid
import datetime
from typing import Any

from posthog.api.capture import capture_batch_internal
from posthog.models import Team

from products.signals.backend.anomaly_scores.queue import SCORE_EVENT, SOURCE_INSIGHT
from products.signals.backend.anomaly_scores.scoring import InsightScores, ScoredPoint, ScoredSeries

EVENT_SOURCE = "signals_anomaly_scores"
# Not a person. Every score event of every project uses it, and no person profile is made for it.
SCORER_DISTINCT_ID = "$posthog_anomaly_scorer"
# A deterministic uuid per series, bucket and scoring version, so a resent bucket replaces its earlier row.
_EVENT_UUID_NAMESPACE = uuid.UUID("6a0f4b9e-2c1d-4e57-9b3a-8d2e1f7c5a40")


def _event(
    *,
    team_id: int,
    insight_id: int,
    scores: InsightScores,
    series: ScoredSeries,
    point: ScoredPoint,
    scored_at: datetime.datetime,
) -> dict[str, Any]:
    bucket_start_utc = point.bucket_start.astimezone(datetime.UTC)
    return {
        "event": SCORE_EVENT,
        "distinct_id": SCORER_DISTINCT_ID,
        # The bucket start, so a trends insight on these events lines up with the source chart.
        "timestamp": bucket_start_utc.isoformat(),
        "event_uuid": str(
            uuid.uuid5(
                _EVENT_UUID_NAMESPACE,
                f"{team_id}:{series.series_key}:{scores.detector_version}:{bucket_start_utc.isoformat()}",
            )
        ),
        "options": {"process_person_profile": False},
        "properties": {
            "$geoip_disable": True,
            "$anomaly_score": point.score,
            "$anomaly_flag": None if point.flag is None else int(point.flag),
            "$anomaly_value": point.value,
            "$anomaly_bucket_start": point.bucket_start.isoformat(),
            "$anomaly_interval": scores.interval.value,
            "$anomaly_series_key": series.series_key,
            "$anomaly_source": SOURCE_INSIGHT,
            "$anomaly_insight_id": insight_id,
            "$anomaly_series_label": series.label,
            "$anomaly_breakdown_value": series.breakdown_value,
            "$anomaly_detector": scores.detector,
            "$anomaly_detector_version": scores.detector_version,
            "$anomaly_profile": scores.profile,
            "$anomaly_scored_at": scored_at.astimezone(datetime.UTC).isoformat(),
            "$anomaly_details": json.dumps(point.details, sort_keys=True),
        },
    }


def score_events(
    *,
    team_id: int,
    insight_id: int,
    scores: InsightScores,
    scored_through: dict[str, datetime.datetime],
    scored_at: datetime.datetime,
) -> list[dict[str, Any]]:
    """One event per series and bucket that is later than the series' newest scored bucket."""
    events: list[dict[str, Any]] = []
    event_uuids: set[str] = set()
    for series in scores.series:
        through = scored_through.get(series.series_key)
        for point in series.points:
            if through is not None and point.bucket_start <= through:
                continue
            event = _event(
                team_id=team_id,
                insight_id=insight_id,
                scores=scores,
                series=series,
                point=point,
                scored_at=scored_at,
            )
            # Capture rejects the whole batch on a repeated uuid, e.g. an hourly bucket repeated at a DST fall-back.
            if event["event_uuid"] in event_uuids:
                continue
            event_uuids.add(event["event_uuid"])
            events.append(event)
    return events


def emit(team: Team, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    capture_batch_internal(
        events=events, token=team.api_token, event_source=EVENT_SOURCE, process_person_profile=False
    ).raise_for_status()
