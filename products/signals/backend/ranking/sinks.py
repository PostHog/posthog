"""Where a scoring pass writes: one `ranking_score` artefact per report, and one event per model.

`ranking_score` is in `NON_WRITABLE_ARTEFACT_TYPES`, so this system path is its only writer. The
events go to PostHog's own project, where the inbox label streams join them on `report_id` like
every other ranking event.
"""

from collections.abc import Sequence
from contextlib import nullcontext

from django.conf import settings

from posthog.ph_client import ScopedCapture, ph_scoped_capture

from products.signals.backend.artefact_schemas import RankingModelResult, RankingScore
from products.signals.backend.models import SignalActorKind, SignalReport, SignalReportArtefact
from products.signals.backend.ranking.model_contract import classification_thresholds, readable_head_names

REPORT_SCORED_EVENT = "inbox_ranking_report_scored"
DISTINCT_ID = "inbox_ranking_scoring"


def persist_scores(
    team_id: int, scores: Sequence[tuple[str, RankingScore]], *, capture: ScopedCapture | None = None
) -> int:
    """Write one artefact per `(report_id, score)` of the team, then capture its events.

    A report id that is not one of the team's reports is dropped. Returns the rows written. Without
    `capture`, the call opens its own scope, which blocks on a flush when it closes. A caller that
    persists many teams passes one `capture` for all of them, so it pays that flush once.
    """
    report_ids = [report_id for report_id, _ in scores]
    owned = {
        str(report_id)
        for report_id in SignalReport.objects.filter(team_id=team_id, id__in=report_ids).values_list("id", flat=True)
    }
    kept = [(report_id, score) for report_id, score in scores if report_id in owned]
    SignalReportArtefact.objects.bulk_create(
        [
            SignalReportArtefact(
                team_id=team_id,
                report_id=report_id,
                type=SignalReportArtefact.ArtefactType.RANKING_SCORE,
                content=score.model_dump_json(),
                actor_kind=SignalActorKind.SYSTEM,
            )
            for report_id, score in kept
        ]
    )
    with ph_scoped_capture() if capture is None else nullcontext(capture) as active_capture:
        for report_id, score in kept:
            for model_key, result in score.results.items():
                active_capture(
                    distinct_id=DISTINCT_ID,
                    event=REPORT_SCORED_EVENT,
                    properties={
                        "$process_person_profile": False,
                        "environment": settings.CLOUD_DEPLOYMENT,
                        "team_id": team_id,
                        "report_id": report_id,
                        "model_key": model_key,
                        "model_name": result.model_name,
                        "model_version": result.model_version,
                        "roles": result.roles,
                        "status": result.status,
                        "skip_reason": result.skip_reason,
                        "manifest_version": score.manifest_version,
                        "embedding_inserted_at": score.embedding_inserted_at.isoformat()
                        if score.embedding_inserted_at
                        else None,
                        **{f"p_{head}": probability for head, probability in result.scores.items()},
                        **classification_properties(result),
                    },
                )
    return len(kept)


def classification_properties(result: RankingModelResult) -> dict[str, object]:
    """The served threshold and the flag it gives, per head, read from the result's copied metadata.

    A serving copy is immutable per model key, so its metadata holds the threshold that scored the
    report. A head without a saved threshold gets neither property: a model trained before
    thresholds existed has none, and no other value may stand in for it. A tie is a positive, as in
    the dag's grade.
    """
    thresholds = classification_thresholds(result.metadata)
    return {
        "readable_heads": sorted(readable_head_names(result.metadata)),
        **{f"threshold_{head}": threshold for head, threshold in thresholds.items()},
        **{
            f"predicted_{head}": probability >= thresholds[head]
            for head, probability in result.scores.items()
            if head in thresholds
        },
    }
