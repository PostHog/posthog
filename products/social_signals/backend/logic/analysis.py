"""Runner that executes the analyzer registry against a Mention.

Designed to be called from a Celery task. Each analyzer's failure is isolated —
a crash in one analyzer doesn't prevent the others from running, and the
mention's overall status reflects the worst per-analyzer outcome.
"""

from __future__ import annotations

import structlog
from django.utils import timezone

from ..analyzers import MentionAnalyzer, get_default_analyzers
from ..facade.enums import AnalysisStatus, ProcessingStatus
from ..models import Mention, MentionAnalysis

logger = structlog.get_logger(__name__)


def run_analyzers_for_mention(mention_id: str) -> None:
    """Run every default analyzer against the mention. Idempotent on
    ``(mention, kind)`` — re-runs overwrite the previous result row.

    Reads the mention with ``all_teams`` because the Celery worker has no
    request context; team scoping is applied per-update.
    """
    try:
        mention = Mention.all_teams.select_related("source").get(id=mention_id)
    except Mention.DoesNotExist:
        logger.warning("social_signals.analyze.mention_missing", mention_id=mention_id)
        return

    Mention.all_teams.filter(id=mention.id).update(
        status=ProcessingStatus.ANALYZING.value, last_error=""
    )

    any_failed = False
    for analyzer_cls in get_default_analyzers():
        succeeded = _run_single(mention, analyzer_cls())
        if not succeeded:
            any_failed = True

    final_status = ProcessingStatus.FAILED if any_failed else ProcessingStatus.DONE
    Mention.all_teams.filter(id=mention.id).update(status=final_status.value)


def _run_single(mention: Mention, analyzer: MentionAnalyzer) -> bool:
    """Run a single analyzer and persist the result row. Returns success."""
    analysis, _ = MentionAnalysis.all_teams.get_or_create(
        mention=mention,
        kind=analyzer.kind,
        defaults={
            "team_id": mention.team_id,
            "status": AnalysisStatus.PENDING.value,
            "model_used": analyzer.model_used,
        },
    )

    try:
        result = analyzer.run(mention)
    except Exception as exc:
        logger.exception(
            "social_signals.analyzer.failed",
            analyzer_kind=analyzer.kind,
            mention_id=str(mention.id),
        )
        MentionAnalysis.all_teams.filter(id=analysis.id).update(
            status=AnalysisStatus.FAILED.value,
            error=str(exc)[:1000],
            updated_at=timezone.now(),
        )
        return False

    MentionAnalysis.all_teams.filter(id=analysis.id).update(
        status=AnalysisStatus.SUCCEEDED.value,
        result=result,
        error="",
        model_used=analyzer.model_used,
        updated_at=timezone.now(),
    )
    return True
