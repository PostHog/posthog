import math
import hashlib
import statistics

import structlog
from temporalio import activity

from posthog.schema import CompareFilter, DateRange, WebNotableChangeItem, WebNotableChangesQuery

from posthog.hogql_queries.web_analytics.notable_changes import WebNotableChangesQueryRunner
from posthog.models import Team
from posthog.models.instance_setting import get_instance_setting
from posthog.sync import database_sync_to_async

from products.signals.backend.api import emit_signal
from products.signals.backend.models import SignalSourceConfig
from products.web_analytics.backend.temporal.notable_changes.types import ProcessTeamBatchInput

logger = structlog.get_logger(__name__)

IMPACT_SCORE_NORMALIZATION_ANCHOR = 500
MIN_WEIGHT = 0.3
MAX_WEIGHT = 1.0


def _build_description(item: WebNotableChangeItem) -> str:
    direction = "increased" if item.percent_change > 0 else "decreased"
    pct = abs(item.percent_change * 100)
    return (
        f"Web analytics notable change: {item.dimension_type} '{item.dimension_value}' "
        f"{direction} by {pct:.0f}% in {item.metric} this week "
        f"(from {item.previous_value:.0f} to {item.current_value:.0f}). "
        f"Impact score: {item.impact_score:.1f}."
    )


def _compute_weight(impact_score: float) -> float:
    raw = math.log1p(max(0.0, impact_score)) / math.log1p(IMPACT_SCORE_NORMALIZATION_ANCHOR)
    scaled = MIN_WEIGHT + (MAX_WEIGHT - MIN_WEIGHT) * raw
    return round(min(MAX_WEIGHT, max(MIN_WEIGHT, scaled)), 2)


def _build_source_id(team_id: int, week_key: str, dimension_type: str, dimension_value: str) -> str:
    value_hash = hashlib.sha256(dimension_value.encode()).hexdigest()[:12]
    return f"web-notable-{team_id}-{week_key}-{dimension_type}-{value_hash}"


def _run_notable_changes_query(query: WebNotableChangesQuery, team: Team) -> list[WebNotableChangeItem]:
    runner = WebNotableChangesQueryRunner(query=query, team=team)
    response = runner.calculate()
    return response.results


@activity.defn
async def get_eligible_team_ids() -> list[int]:
    @database_sync_to_async(thread_sensitive=False)
    def _query() -> tuple[list[int], list[int]]:
        allowed_ids: list[int] = get_instance_setting("WEB_NOTABLE_CHANGES_ALLOWED_TEAM_IDS")
        qs = (
            Team.objects.filter(
                organization__is_ai_data_processing_approved=True,
            )
            .exclude(is_demo=True)
            .exclude(organization__for_internal_metrics=True)
        )
        if allowed_ids:
            qs = qs.filter(id__in=allowed_ids)
        return list(qs.values_list("id", flat=True)), allowed_ids

    team_ids, allowed_ids = await _query()

    if allowed_ids:
        await logger.ainfo(
            "Filtered to allowed teams for notable changes", allowed=len(allowed_ids), count=len(team_ids)
        )
    else:
        await logger.ainfo("Found eligible teams for notable changes", count=len(team_ids))

    return team_ids


@activity.defn
async def process_team_batch(input: ProcessTeamBatchInput) -> None:
    @database_sync_to_async(thread_sensitive=False)
    def _fetch_teams() -> dict[int, Team]:
        return {t.id: t for t in Team.objects.filter(id__in=input.team_ids).select_related("organization")}

    @database_sync_to_async(thread_sensitive=False)
    def _fetch_emit_team_ids() -> set[int]:
        return set(get_instance_setting("WEB_NOTABLE_CHANGES_EMIT_TEAM_IDS") or [])

    teams_by_id = await _fetch_teams()
    emit_team_ids = await _fetch_emit_team_ids()

    # Process teams sequentially inside a batch: each team runs a ClickHouse
    # query and emits N signals, and we want to bound concurrent load on
    # ClickHouse + the signals write path. Parallelism lives at the batch level.
    for team_id in input.team_ids:
        team = teams_by_id.get(team_id)
        if team is None:
            await logger.awarning("Team not found, skipping", team_id=team_id)
            continue

        emitted = team_id in emit_team_ids

        try:
            query = WebNotableChangesQuery(
                dateRange=DateRange(date_from="-7d"),
                compareFilter=CompareFilter(compare=True),
                properties=[],
                filterTestAccounts=True,
                doPathCleaning=True,
                limit=input.limit_per_team,
            )

            results = await database_sync_to_async(_run_notable_changes_query, thread_sensitive=False)(query, team)

            weights: list[float] = []
            impact_scores: list[float] = []

            for item in results:
                source_id = _build_source_id(team_id, input.week_key, item.dimension_type, item.dimension_value)
                description = _build_description(item)
                weight = _compute_weight(item.impact_score)
                weights.append(weight)
                impact_scores.append(item.impact_score)

                if emitted:
                    await emit_signal(
                        team=team,
                        source_product=SignalSourceConfig.SourceProduct.WEB_ANALYTICS,
                        source_type=SignalSourceConfig.SourceType.NOTABLE_CHANGE,
                        source_id=source_id,
                        description=description,
                        weight=weight,
                        extra={
                            "dimension_type": item.dimension_type,
                            "dimension_value": item.dimension_value,
                            "metric": item.metric,
                            "current_value": item.current_value,
                            "previous_value": item.previous_value,
                            "percent_change": item.percent_change,
                            "impact_score": item.impact_score,
                            "week_start": input.week_start_iso,
                        },
                    )
                else:
                    await logger.ainfo(
                        "Shadow notable change",
                        team_id=team_id,
                        source_id=source_id,
                        weight=weight,
                        impact_score=item.impact_score,
                        dimension_type=item.dimension_type,
                        dimension_value=item.dimension_value,
                        metric=item.metric,
                        percent_change=item.percent_change,
                    )

            await logger.ainfo(
                "Processed notable changes for team",
                team_id=team_id,
                signal_count=len(results),
                emitted=emitted,
                weight_stats=_summarize(weights),
                impact_score_stats=_summarize(impact_scores),
            )

        except Exception:
            await logger.aexception("Failed to process notable changes for team", team_id=team_id)
        finally:
            activity.heartbeat()


def _summarize(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(statistics.fmean(values), 4),
    }
