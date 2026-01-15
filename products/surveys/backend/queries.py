from datetime import timedelta
from typing import TypedDict

from django.db.models import Count, Q, QuerySet
from django.utils import timezone

import structlog

from posthog.models import Experiment, FeatureFlag, Insight, Team

logger = structlog.get_logger(__name__)


class FunnelStep(TypedDict):
    index: int
    event: str | None
    action_id: int | None
    label: str


class InsightCandidate(TypedDict):
    insight_id: int
    insight_name: str
    short_id: str
    view_count: int
    unique_viewers: int
    insight_type: str  # 'funnel', 'trend', 'retention', etc.


class FunnelInsightCandidate(InsightCandidate):
    steps: list[FunnelStep]


class VariantInfo(TypedDict):
    key: str
    name: str | None
    rollout_percentage: int


class ExperimentCandidate(TypedDict):
    experiment_id: int
    experiment_name: str
    feature_flag_key: str
    start_date: str | None
    end_date: str | None
    is_complete: bool
    variants: list[VariantInfo]


class FeatureFlagCandidate(TypedDict):
    flag_id: int
    flag_key: str
    flag_name: str
    rollout_percentage: int | None
    is_fully_rolled_out: bool
    variants: list[VariantInfo]


def get_insight_type(query: dict) -> str:
    source = query.get("source", query)
    kind = source.get("kind", "")

    type_map = {
        "FunnelsQuery": "funnel",
        "TrendsQuery": "trend",
        "RetentionQuery": "retention",
        "PathsQuery": "paths",
        "StickinessQuery": "stickiness",
        "LifecycleQuery": "lifecycle",
    }

    return type_map.get(kind, "unknown")


def _build_funnel_step(index: int, step: dict) -> FunnelStep:
    step_kind = step.get("kind", "")
    default_label = f"Step {index + 1}"

    if step_kind == "EventsNode":
        event = step.get("event") or step.get("name")
        return {
            "index": index,
            "event": event,
            "action_id": None,
            "label": step.get("custom_name") or event or default_label,
        }

    if step_kind == "ActionsNode":
        action_id = step.get("id")
        return {
            "index": index,
            "event": None,
            "action_id": action_id,
            "label": step.get("custom_name") or step.get("name") or f"Action {action_id}",
        }

    return {
        "index": index,
        "event": None,
        "action_id": None,
        "label": default_label,
    }


def extract_funnel_steps(query: dict | None) -> list[FunnelStep]:
    if not query:
        return []

    source = query.get("source", query) if query.get("kind") == "InsightVizNode" else query

    if source.get("kind") != "FunnelsQuery":
        return []

    series = source.get("series", [])
    return [_build_funnel_step(i, step) for i, step in enumerate(series)]


def _get_most_viewed_insights(
    team: Team,
    query_kind: str,
    filter_value: str,
    days: int,
    limit: int,
) -> QuerySet[Insight]:
    cutoff_date = timezone.now() - timedelta(days=days)

    return (
        Insight.objects.filter(
            team=team,
            deleted=False,
            saved=True,
        )
        .filter(Q(query__kind=query_kind) | Q(query__source__kind=query_kind) | Q(filters__insight=filter_value))
        .filter(
            insightviewed__last_viewed_at__gte=cutoff_date,
            insightviewed__team=team,
        )
        .annotate(
            view_count=Count("insightviewed", filter=Q(insightviewed__last_viewed_at__gte=cutoff_date)),
            unique_viewers=Count(
                "insightviewed__user",
                filter=Q(insightviewed__last_viewed_at__gte=cutoff_date),
                distinct=True,
            ),
        )
        .order_by("-view_count")[:limit]
    )


def _insight_name(insight: Insight) -> str:
    return insight.name or insight.derived_name or "Untitled"


def get_most_viewed_funnels(
    team: Team,
    days: int = 30,
    limit: int = 20,
) -> list[FunnelInsightCandidate]:
    insights = _get_most_viewed_insights(
        team=team,
        query_kind="FunnelsQuery",
        filter_value="FUNNELS",
        days=days,
        limit=limit,
    )

    return [
        {
            "insight_id": insight.id,
            "insight_name": _insight_name(insight),
            "short_id": insight.short_id,
            "view_count": insight.view_count,
            "unique_viewers": insight.unique_viewers,
            "insight_type": "funnel",
            "steps": extract_funnel_steps(insight.query),
        }
        for insight in insights
    ]


def get_most_viewed_trends(
    team: Team,
    days: int = 30,
    limit: int = 20,
) -> list[InsightCandidate]:
    insights = _get_most_viewed_insights(
        team=team,
        query_kind="TrendsQuery",
        filter_value="TRENDS",
        days=days,
        limit=limit,
    )

    return [
        {
            "insight_id": insight.id,
            "insight_name": _insight_name(insight),
            "short_id": insight.short_id,
            "view_count": insight.view_count,
            "unique_viewers": insight.unique_viewers,
            "insight_type": "trend",
        }
        for insight in insights
    ]


def _experiment_to_candidate(exp: Experiment, is_complete: bool) -> ExperimentCandidate:
    return {
        "experiment_id": exp.id,
        "experiment_name": exp.name,
        "feature_flag_key": exp.feature_flag.key if exp.feature_flag else "",
        "start_date": exp.start_date.isoformat() if exp.start_date else None,
        "end_date": exp.end_date.isoformat() if exp.end_date else None,
        "is_complete": is_complete,
        "variants": _get_flag_variants(exp.feature_flag) if exp.feature_flag else [],
    }


def get_recently_concluded_experiments(
    team: Team,
    days: int = 60,
    limit: int = 10,
) -> list[ExperimentCandidate]:
    cutoff_date = timezone.now() - timedelta(days=days)

    experiments = (
        Experiment.objects.filter(
            team=team,
            end_date__gte=cutoff_date,
            end_date__lte=timezone.now(),
        )
        .select_related("feature_flag")
        .order_by("-end_date")[:limit]
    )

    return [_experiment_to_candidate(exp, is_complete=True) for exp in experiments]


def get_running_experiments(
    team: Team,
    limit: int = 10,
) -> list[ExperimentCandidate]:
    now = timezone.now()

    experiments = (
        Experiment.objects.filter(
            team=team,
            start_date__lte=now,
        )
        .filter(Q(end_date__isnull=True) | Q(end_date__gt=now))
        .select_related("feature_flag")
        .order_by("-start_date")[:limit]
    )

    return [_experiment_to_candidate(exp, is_complete=False) for exp in experiments]


def _get_rollout_percentage(flag: FeatureFlag) -> int | None:
    if not flag.filters:
        return None
    groups = flag.filters.get("groups", [])
    if not groups:
        return None
    return groups[0].get("rollout_percentage")


def _get_flag_variants(flag: FeatureFlag) -> list[VariantInfo]:
    if not flag.filters:
        return []
    multivariate = flag.filters.get("multivariate", {})
    raw_variants = multivariate.get("variants", [])
    return [
        {
            "key": v.get("key", ""),
            "name": v.get("name"),
            "rollout_percentage": v.get("rollout_percentage", 0),
        }
        for v in raw_variants
    ]


def get_recently_rolled_out_flags(
    team: Team,
    days: int = 30,
    limit: int = 10,
) -> list[FeatureFlagCandidate]:
    cutoff_date = timezone.now() - timedelta(days=days)

    flags = (
        FeatureFlag.objects.filter(
            team=team,
            deleted=False,
            active=True,
            updated_at__gte=cutoff_date,
            filters__groups__0__rollout_percentage=100,
        )
        .exclude(experiment__isnull=False)
        .order_by("-updated_at")[:limit]
    )

    return [
        {
            "flag_id": flag.id,
            "flag_key": flag.key,
            "flag_name": flag.name or flag.key,
            "rollout_percentage": (rollout := _get_rollout_percentage(flag)),
            "is_fully_rolled_out": rollout == 100,
            "variants": _get_flag_variants(flag),
        }
        for flag in flags
    ]


class SurveyRecommendationCandidates(TypedDict):
    most_viewed_funnels: list[FunnelInsightCandidate]
    most_viewed_trends: list[InsightCandidate]
    concluded_experiments: list[ExperimentCandidate]
    running_experiments: list[ExperimentCandidate]
    rolled_out_flags: list[FeatureFlagCandidate]


def get_survey_recommendation_candidates(team: Team) -> SurveyRecommendationCandidates:
    return {
        "most_viewed_funnels": get_most_viewed_funnels(team, days=30, limit=10),
        "most_viewed_trends": get_most_viewed_trends(team, days=30, limit=10),
        "concluded_experiments": get_recently_concluded_experiments(team, days=60, limit=5),
        "running_experiments": get_running_experiments(team, limit=5),
        "rolled_out_flags": get_recently_rolled_out_flags(team, days=30, limit=5),
    }
