"""When a served ranking score no longer describes the report's text.

A score is stale when the report's title or summary was edited after the vector the score read.
Only the two edit paths (the report PATCH and the scout `edit_report` tool) write the edit
artefacts, so the pipeline's own rewrites never mark a score stale.

The time a score is compared against is the landing time of the vector it read, not `scored_at`.
`scored_at` is the start of the sweep pass, and a team's vectors are read later in the pass. An
edit that is indexed in that gap gives a score on the new text with a `scored_at` before the edit.
The vector lands after the commit of the edit that produced it, so a vector newer than the edit
holds the edited text. A score with no vector time falls back to `scored_at`.

Staleness is information only. A stale score still sorts, filters and shows like a fresh one,
because most edits do not change what a report is about.
"""

from datetime import datetime

from products.signals.backend.artefact_schemas import RankingScore
from products.signals.backend.models import SignalReportArtefact

EDIT_ARTEFACT_TYPES: tuple[str, ...] = (
    SignalReportArtefact.ArtefactType.TITLE_CHANGE,
    SignalReportArtefact.ArtefactType.SUMMARY_CHANGE,
)


def score_read_at(score: RankingScore) -> datetime:
    """The time of the text the score describes."""
    return score.embedding_inserted_at or score.scored_at


def is_stale_score(score: RankingScore, latest_edit_at: datetime | None) -> bool:
    read_at = score_read_at(score)
    # A naive time has no fixed instant to compare, so it reads as not stale.
    if latest_edit_at is None or read_at.tzinfo is None:
        return False
    return latest_edit_at > read_at
