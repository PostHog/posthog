import json
from collections.abc import Mapping
from uuid import UUID

from django.db import transaction

from posthog.dataclasses import frozen

from products.signals.backend.artefact_schemas import RankingScore, priority_from_judgment
from products.signals.backend.models import AutonomyPriority, SignalReport, SignalReportArtefact

PUBLIC_SCORE_FIELDS: Mapping[str, str] = {
    "open": "ranking_open_score",
    "action": "ranking_action_score",
    "fixed": "ranking_fix_score",
}
PUBLIC_LIFT_FIELDS: Mapping[str, str] = {
    "open": "ranking_open_lift",
    "action": "ranking_action_lift",
    "fixed": "ranking_fix_lift",
}
RANKING_CACHE_FIELDS = ["ranking_scores", *PUBLIC_SCORE_FIELDS.values(), *PUBLIC_LIFT_FIELDS.values()]


@frozen
class _RankingValues:
    scores: Mapping[str, float]
    lifts: Mapping[str, float]


def _numbers(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {
        key: float(number)
        for key, number in value.items()
        if isinstance(key, str) and isinstance(number, (int, float)) and not isinstance(number, bool)
    }


def ranking_values_from_content(content: str | None) -> _RankingValues:
    try:
        parsed = json.loads(content or "")
    except (json.JSONDecodeError, TypeError, ValueError):
        return _RankingValues(scores={}, lifts={})
    if not isinstance(parsed, dict):
        return _RankingValues(scores={}, lifts={})

    served_key = parsed.get("served_key")
    results = parsed.get("results")
    served = results.get(served_key) if isinstance(results, dict) and isinstance(served_key, str) else None
    if not isinstance(served, dict):
        return _RankingValues(scores={}, lifts={})
    return _RankingValues(scores=_numbers(served.get("scores")), lifts=_numbers(served.get("lifts")))


def apply_ranking_cache(report: SignalReport, score: RankingScore | None) -> None:
    scores: Mapping[str, float] = {}
    lifts: Mapping[str, float] = {}
    if score is not None:
        served = score.results.get(score.served_key)
        if served is not None:
            scores = served.scores
            lifts = served.lifts

    _apply_ranking_values(report, scores, lifts)


def _apply_ranking_values(report: SignalReport, scores: Mapping[str, float], lifts: Mapping[str, float]) -> None:
    report.ranking_scores = dict(scores) or None
    for head, field in PUBLIC_SCORE_FIELDS.items():
        setattr(report, field, scores.get(head))
    for head, field in PUBLIC_LIFT_FIELDS.items():
        setattr(report, field, lifts.get(head))


def refresh_report_ranking_cache(*, team_id: int, report_id: UUID | str) -> bool:
    with transaction.atomic():
        report = (
            SignalReport.objects.select_for_update(no_key=True)
            .filter(team_id=team_id, id=report_id)
            .only(*RANKING_CACHE_FIELDS)
            .first()
        )
        if report is None:
            return False
        artefact = (
            SignalReportArtefact.objects.filter(
                report_id=report_id, type=SignalReportArtefact.ArtefactType.RANKING_SCORE
            )
            .order_by("-created_at", "-id")
            .only("content")
            .first()
        )
        previous = tuple(getattr(report, field) for field in RANKING_CACHE_FIELDS)
        values = ranking_values_from_content(artefact.content if artefact is not None else None)
        _apply_ranking_values(report, values.scores, values.lifts)
        if previous == tuple(getattr(report, field) for field in RANKING_CACHE_FIELDS):
            return False
        SignalReport.objects.filter(team_id=team_id, id=report_id).update(
            **{field: getattr(report, field) for field in RANKING_CACHE_FIELDS}
        )
        return True


def backfill_report_sort_cache(*, team_id: int, batch_size: int = 500) -> int:
    cursor: UUID | None = None
    updated = 0
    while True:
        with transaction.atomic():
            page = SignalReport.objects.filter(team_id=team_id).select_for_update(no_key=True).order_by("id")
            if cursor is not None:
                page = page.filter(id__gt=cursor)
            reports = list(page[:batch_size])
            if not reports:
                return updated
            cursor = reports[-1].id
            report_ids = [str(report.id) for report in reports]
            priorities = dict(
                SignalReportArtefact.objects.filter(
                    team_id=team_id,
                    report_id__in=report_ids,
                    type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
                    content__startswith="{",
                )
                .order_by("report_id", "-created_at", "-id")
                .distinct("report_id")
                .values_list("report_id", "content")
            )
            scores = dict(
                SignalReportArtefact.objects.filter(
                    team_id=team_id, report_id__in=report_ids, type=SignalReportArtefact.ArtefactType.RANKING_SCORE
                )
                .order_by("report_id", "-created_at", "-id")
                .distinct("report_id")
                .values_list("report_id", "content")
            )
            for report in reports:
                priority = priority_from_judgment(priorities.get(report.id))
                report.priority_sort_rank = (
                    AutonomyPriority.values.index(priority)
                    if priority in AutonomyPriority.values
                    else len(AutonomyPriority.values)
                )
                values = ranking_values_from_content(scores.get(report.id))
                _apply_ranking_values(report, values.scores, values.lifts)
            SignalReport.objects.filter(team_id=team_id).bulk_update(
                reports, ["priority_sort_rank", *RANKING_CACHE_FIELDS], batch_size=batch_size
            )
            updated += len(reports)
