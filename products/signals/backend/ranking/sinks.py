"""Where a scoring pass writes: one `ranking_score` artefact per report, and one event per model.

`ranking_score` is in `NON_WRITABLE_ARTEFACT_TYPES`, so this system path is its only writer. The
events go to PostHog's own project, where the inbox label streams join them on `report_id` like
every other ranking event.
"""

from collections.abc import Sequence

from django.conf import settings

from posthog.ph_client import ph_scoped_capture

from products.signals.backend.artefact_schemas import RankingScore
from products.signals.backend.models import SignalActorKind, SignalReport, SignalReportArtefact

REPORT_SCORED_EVENT = "inbox_ranking_report_scored"
DISTINCT_ID = "inbox_ranking_scoring"


def persist_scores(team_id: int, scores: Sequence[tuple[str, RankingScore]]) -> int:
    """Write one artefact per `(report_id, score)` of the team, then capture its events.

    A report id that is not one of the team's reports is dropped. Returns the rows written.
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
    with ph_scoped_capture() as capture:
        for report_id, score in kept:
            for model_key, result in score.results.items():
                capture(
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
                    },
                )
    return len(kept)
