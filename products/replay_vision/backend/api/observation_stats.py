"""Aggregate counts and per-type distributions for a scanner's observation set.

All aggregations run in Postgres — status/coverage/verdict via ORM, classifier tag rankings and scorer
summary+histogram via raw SQL (`jsonb_array_elements_text`, `PERCENTILE_CONT`).
"""

import math
from datetime import timedelta
from typing import Any, Literal, get_args

from django.db import connection
from django.db.models import Count, Max, Min, Q, QuerySet
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import TruncDate
from django.utils import timezone

from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType
from products.replay_vision.backend.temporal.scanners.monitor import MonitorVerdict

_DEFAULT_RECENT_DAYS = 14
_MAX_RECENT_DAYS = 365
_HISTOGRAM_BUCKET_TARGET = 21
_TOP_TAGS = 10


def compute_observation_stats(
    scanner: ReplayScanner,
    queryset: QuerySet[ReplayObservation],
    recent_days: int = _DEFAULT_RECENT_DAYS,
) -> dict[str, Any]:
    # Clamp so a hostile or stale client can't ask for "last 9,999 days" or 0.
    clamped_recent_days = max(1, min(recent_days, _MAX_RECENT_DAYS))
    status_counts = _status_counts(queryset)
    payload: dict[str, Any] = {
        "status_counts": status_counts,
        "coverage": _coverage(queryset, clamped_recent_days),
        "labels": _label_stats(queryset, clamped_recent_days),
        "available_tags": [],
        "monitor": None,
        "classifier": None,
        "scorer": None,
    }

    if scanner.scanner_type == ScannerType.MONITOR:
        payload["monitor"] = _monitor_stats(queryset)
    elif scanner.scanner_type == ScannerType.CLASSIFIER:
        classifier, available_tags = _classifier_stats(queryset)
        payload["classifier"] = classifier
        payload["available_tags"] = available_tags
    elif scanner.scanner_type == ScannerType.SCORER:
        payload["scorer"] = _scorer_stats(scanner, queryset)

    return payload


def _status_counts(queryset: QuerySet[ReplayObservation]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    # `.order_by()` so the parent ordering doesn't leak into GROUP BY.
    for row in queryset.order_by().values("status").annotate(c=Count("*")):
        counts[row["status"]] = row["c"]
    succeeded = counts.get(ObservationStatus.SUCCEEDED, 0)
    failed = counts.get(ObservationStatus.FAILED, 0)
    ineligible = counts.get(ObservationStatus.INELIGIBLE, 0)
    in_flight = counts.get(ObservationStatus.PENDING, 0) + counts.get(ObservationStatus.RUNNING, 0)
    scored = succeeded + failed
    return {
        "total": sum(counts.values()),
        "succeeded": succeeded,
        "failed": failed,
        "ineligible": ineligible,
        "in_flight": in_flight,
        # Success rate excludes ineligible: those were skipped at the gate, not scanner failures.
        "success_rate": round(succeeded / scored * 100) if scored else None,
    }


def _coverage(queryset: QuerySet[ReplayObservation], recent_days: int) -> dict[str, Any]:
    cutoff = timezone.now() - timedelta(days=recent_days)
    with_sessions = queryset.exclude(session_id="")
    aggregates = with_sessions.aggregate(
        total=Count("session_id", distinct=True),
        recent=Count("session_id", filter=Q(created_at__gte=cutoff), distinct=True),
    )
    return {
        "recent_sessions": aggregates["recent"] or 0,
        "total_sessions": aggregates["total"] or 0,
        "recent_days": recent_days,
    }


def _label_day_counts(
    labeled: QuerySet[ReplayObservation], day_field: Literal["created_at", "label__updated_at"], cutoff: Any
) -> list[dict[str, Any]]:
    # Explicit branches (not a dynamic **{f"{field}__gte"} key) so ORM field names stay static.
    if day_field == "created_at":
        windowed = labeled.filter(created_at__gte=cutoff)
    else:
        windowed = labeled.filter(label__updated_at__gte=cutoff)
    rows = (
        windowed.annotate(day=TruncDate(day_field))
        .order_by()  # Don't let parent ordering leak into GROUP BY.
        .values("day")
        .annotate(
            up=Count("id", filter=Q(label__is_correct=True)),
            down=Count("id", filter=Q(label__is_correct=False)),
        )
        .order_by("day")
    )
    return [{"date": row["day"], "up": row["up"], "down": row["down"]} for row in rows]


def _version_markers(queryset: QuerySet[ReplayObservation]) -> list[dict[str, Any]]:
    """Every prompt version that produced observations, with its first day, prompt text (from the run
    snapshot), and rating counts. All-time: charts window it client-side; the configuration overview
    shows the full history."""
    rows = (
        queryset.annotate(snapshot_version=KeyTextTransform("scanner_version", "scanner_snapshot"))
        .exclude(snapshot_version=None)
        .annotate(
            day=TruncDate("created_at"),
            snapshot_prompt=KeyTextTransform("prompt", KeyTextTransform("scanner_config", "scanner_snapshot")),
        )
        .order_by()
        .values("snapshot_version")
        .annotate(
            first_day=Min("day"),
            prompt=Max("snapshot_prompt"),
            up=Count("id", filter=Q(label__is_correct=True)),
            down=Count("id", filter=Q(label__is_correct=False)),
            # Only succeeded observations can be rated, so they are the ratable "scanned" total.
            total=Count("id", filter=Q(status=ObservationStatus.SUCCEEDED)),
        )
    )
    markers = []
    for row in rows:
        try:
            version = int(row["snapshot_version"])
        except (TypeError, ValueError):
            continue
        markers.append(
            {
                "date": row["first_day"],
                "version": version,
                "prompt": row["prompt"] or "",
                "up": row["up"],
                "down": row["down"],
                "total": row["total"],
            }
        )
    return sorted(markers, key=lambda marker: (marker["date"], marker["version"]))


def _label_stats(queryset: QuerySet[ReplayObservation], recent_days: int) -> dict[str, Any]:
    labeled = queryset.filter(label__isnull=False)
    totals = labeled.aggregate(
        up=Count("id", filter=Q(label__is_correct=True)),
        down=Count("id", filter=Q(label__is_correct=False)),
    )
    # UTC midnight so the window is exactly the `recent_days` calendar days the client charts;
    # a rolling now-based cutoff would return a boundary day the chart then drops.
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = today_start - timedelta(days=recent_days - 1)
    return {
        "up_total": totals["up"] or 0,
        "down_total": totals["down"] or 0,
        # Bucketed by the day the session was scanned, so the series tracks scanner quality over time:
        # as the prompt improves, newer days should carry fewer thumbs-down.
        "by_day": _label_day_counts(labeled, "created_at", cutoff),
        # Bucketed by the day the rating was last set or changed: the team's rating activity.
        "by_rating_day": _label_day_counts(labeled, "label__updated_at", cutoff),
        "version_markers": _version_markers(queryset),
    }


def _monitor_stats(queryset: QuerySet[ReplayObservation]) -> dict[str, Any]:
    counts = dict.fromkeys(get_args(MonitorVerdict), 0)
    rows = (
        queryset.filter(status=ObservationStatus.SUCCEEDED)
        .annotate(verdict=KeyTextTransform("verdict", KeyTextTransform("model_output", "scanner_result")))
        .filter(verdict__in=counts.keys())
        .order_by()  # Don't let parent ordering leak into GROUP BY.
        .values("verdict")
        .annotate(c=Count("*"))
    )
    for row in rows:
        counts[row["verdict"]] = row["c"]
    return {
        "yes_total": counts["yes"],
        "no_total": counts["no"],
        "inconclusive_total": counts["inconclusive"],
    }


def _classifier_stats(queryset: QuerySet[ReplayObservation]) -> tuple[dict[str, Any], list[str]]:
    # `.order_by()` skips a wasted sort inside the CTE; the outer aggregate doesn't need ordering.
    succeeded = queryset.filter(status=ObservationStatus.SUCCEEDED).order_by()
    inner_sql, inner_params = succeeded.values("scanner_result").query.sql_with_params()
    # One query: per-bucket tag counts plus a sentinel `total` row counting observations that emitted any tag.
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            WITH succeeded AS ({inner_sql})
            SELECT 'fixed' AS bucket, tag, COUNT(*) AS c
            FROM succeeded s, jsonb_array_elements_text(
                COALESCE(s.scanner_result -> 'model_output' -> 'tags', '[]'::jsonb)
            ) AS tag
            GROUP BY tag
            UNION ALL
            SELECT 'freeform' AS bucket, tag, COUNT(*) AS c
            FROM succeeded s, jsonb_array_elements_text(
                COALESCE(s.scanner_result -> 'model_output' -> 'tags_freeform', '[]'::jsonb)
            ) AS tag
            GROUP BY tag
            UNION ALL
            SELECT 'total' AS bucket, NULL AS tag, COUNT(*) AS c FROM succeeded s
            WHERE COALESCE(jsonb_array_length(s.scanner_result -> 'model_output' -> 'tags'), 0) > 0
               OR COALESCE(jsonb_array_length(s.scanner_result -> 'model_output' -> 'tags_freeform'), 0) > 0
            """,
            inner_params,
        )
        rows = cursor.fetchall()

    fixed_counts: dict[str, int] = {}
    freeform_counts: dict[str, int] = {}
    total_with_tags = 0
    for bucket, tag, count in rows:
        if bucket == "total":
            total_with_tags = count
        elif tag is not None:
            target = fixed_counts if bucket == "fixed" else freeform_counts
            target[tag] = target.get(tag, 0) + count

    available_tags = sorted(set(fixed_counts.keys()) | set(freeform_counts.keys()))
    return (
        {
            "fixed_ranked": _rank_counts(fixed_counts),
            "freeform_ranked": _rank_counts(freeform_counts),
            "total_with_tags": total_with_tags,
        },
        available_tags,
    )


def _rank_counts(counts: dict[str, int]) -> list[dict[str, Any]]:
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:_TOP_TAGS]
    return [{"tag": tag, "count": count} for tag, count in items]


def _scorer_stats(scanner: ReplayScanner, queryset: QuerySet[ReplayObservation]) -> dict[str, Any]:
    # `.order_by()` skips a wasted sort inside the subquery; the outer aggregate doesn't need ordering.
    succeeded = queryset.filter(status=ObservationStatus.SUCCEEDED).order_by()
    inner_sql, inner_params = succeeded.values("scanner_result").query.sql_with_params()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            WITH scored AS (
                SELECT ((scanner_result -> 'model_output' ->> 'score')::float) AS score
                FROM ({inner_sql}) s
                WHERE jsonb_typeof(scanner_result -> 'model_output' -> 'score') = 'number'
            )
            SELECT
                COUNT(*),
                MIN(score), MAX(score), AVG(score),
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY score),
                PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY score),
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY score)
            FROM scored
            """,
            inner_params,
        )
        count, lo, hi, mean, p25, median, p75 = cursor.fetchone()
    if not count:
        return {"summary": None, "histogram": None}

    # Span the configured scale (falling back to observed range) so clustered scores still show the full axis.
    config = scanner.scanner_config if isinstance(scanner.scanner_config, dict) else {}
    scale_obj = config.get("scale") if isinstance(config.get("scale"), dict) else None
    scale_min = scale_obj.get("min") if scale_obj else None
    scale_max = scale_obj.get("max") if scale_obj else None
    bucket_lo = math.floor(scale_min) if isinstance(scale_min, (int, float)) else math.floor(lo)
    bucket_hi = math.ceil(scale_max) if isinstance(scale_max, (int, float)) else math.ceil(hi)
    span = max(0, bucket_hi - bucket_lo)
    bucket_width = max(1, math.ceil((span + 1) / _HISTOGRAM_BUCKET_TARGET))
    bucket_count = math.floor(span / bucket_width) + 1

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            WITH scored AS (
                SELECT ((scanner_result -> 'model_output' ->> 'score')::float) AS score
                FROM ({inner_sql}) s
                WHERE jsonb_typeof(scanner_result -> 'model_output' -> 'score') = 'number'
            )
            SELECT
                LEAST(
                    GREATEST(FLOOR((ROUND(score) - %s) / %s)::int, 0),
                    %s
                ) AS bucket,
                COUNT(*)
            FROM scored
            GROUP BY bucket
            ORDER BY bucket
            """,
            (*inner_params, bucket_lo, bucket_width, bucket_count - 1),
        )
        bucket_rows = cursor.fetchall()

    counts = [0] * bucket_count
    for bucket, c in bucket_rows:
        counts[bucket] = c
    labels: list[str] = []
    for i in range(bucket_count):
        start = bucket_lo + i * bucket_width
        if bucket_width == 1:
            labels.append(str(start))
        else:
            labels.append(f"{start}–{min(start + bucket_width - 1, bucket_hi)}")

    return {
        "summary": {
            "min": lo,
            "p25": p25,
            "median": median,
            "mean": mean,
            "p75": p75,
            "max": hi,
            "count": count,
        },
        "histogram": {"labels": labels, "counts": counts},
    }
