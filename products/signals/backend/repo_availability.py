"""Repository availability gate for report promotion.

Repo selection ends without a repository two ways, and only one of them is a question a person can
answer per report. When the selection agent runs and matches nothing, that is about this report's
content. When no GitHub source resolves for the team at all, every report the project promotes
reaches the same dead end, so asking again on each one turns the whole inbox into one repeated
question.

This module reads the standing half of that: the team was already asked to connect a repository,
and still has no source to select from. The gate runs at promotion, next to the quota and
daily-limit gates, so a project without a code host spends no summary run on a report that cannot
get past selection. The first such report still promotes and raises the ask; the rest are held with
their status untouched, and the first matching signal after a source is connected re-evaluates
promotion under the normal rules.

Fails open on any error, like its sibling gates: an infra blip lets work through rather than
holding the pipeline shut.
"""

from typing import TYPE_CHECKING

from django.utils import timezone

import structlog
import posthoganalytics

from posthog.event_usage import groups

from products.signals.backend.models import SignalTeamConfig
from products.tasks.backend.facade.repo_selection import resolve_team_github_integration

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)

# Every pending reason the summary workflow uses for the repo-selection dead end starts with this.
# Matched as a prefix so a reason that names which exit produced it still counts as the same ask.
REPO_SELECTION_PENDING_REASON_PREFIX = "repo_selection_required"


def repo_ask_holds_promotion(team: "Team") -> bool:
    """Whether a report reaching promotion now should be held rather than researched.

    True only for a team that carries an open repo-selection ask and still has no GitHub source, so
    the first report on a repo-less team is let through — it is what raises the ask. A team with no
    stamp pays a single indexed read, which keeps the fleet-wide hot path cheap: there is nothing to
    hold and nothing to clear, so the source never has to be resolved.

    Where the stamp is set and a source does resolve, the team reconnected. The stamp is cleared
    here, which is the only write this gate makes, so a team that disconnects later is asked afresh
    instead of being held silently. Resolves the same source repo selection resolves, including the
    organization-owner fallback, so the gate holds a report only where selection would have found
    nothing to choose from.

    Blocking database I/O; wrap in `database_sync_to_async` from async code.
    """
    try:
        ask_raised_at = (
            SignalTeamConfig.objects.filter(team_id=team.id)
            .values_list("repo_selection_ask_raised_at", flat=True)
            .first()
        )
        if ask_raised_at is None:
            return False
        if resolve_team_github_integration(team.id, team=team) is not None:
            SignalTeamConfig.objects.filter(team_id=team.id).update(repo_selection_ask_raised_at=None)
            return False
        return True
    except Exception:
        logger.warning("signals_repo_availability_check_failed_open", team_id=team.id, exc_info=True)
        return False


def note_repo_selection_ask_raised(team_id: int, *, pending_reason: str | None) -> None:
    """Record the most recent ask, when `pending_reason` says the report stopped at repo selection.

    Called where the report is marked pending, so the stamp only records an ask a person can
    actually see. Two conditions have to hold. The reason has to be the repo-selection dead end,
    because a report the agent researched and then asked about says nothing about the team's
    repositories. And no source may resolve, because a selection that ran and matched nothing is a
    question about this report, and holding the team's other reports over it would hide findings
    whose repository selection could have picked.

    Best-effort — a bookkeeping write must never fail the transition that surfaces the report.
    """
    if pending_reason is None or not pending_reason.startswith(REPO_SELECTION_PENDING_REASON_PREFIX):
        return
    try:
        if resolve_team_github_integration(team_id) is not None:
            return
        SignalTeamConfig.objects.update_or_create(
            team_id=team_id, defaults={"repo_selection_ask_raised_at": timezone.now()}
        )
    except Exception:
        logger.warning("signals_repo_selection_ask_stamp_failed", team_id=team_id, exc_info=True)


def capture_signal_report_repo_ask_held(team: "Team", *, report_id: str | None) -> None:
    """`signal_report_repo_ask_held`: a promotion was held because the team has no GitHub source and
    already carries the repo-selection ask. Measures the withheld report volume, so the held share
    is readable next to the `pending_input` reports the ask itself produces. Best-effort: telemetry
    must never fail the pipeline step that emitted it. Requires `team.organization` to be loaded.
    """
    try:
        posthoganalytics.capture(
            event="signal_report_repo_ask_held",
            distinct_id=str(team.uuid),
            properties={
                "team_id": team.id,
                "organization_id": str(team.organization_id),
                "report_id": report_id,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.exception("Failed to capture signal_report_repo_ask_held", report_id=report_id, team_id=team.id)
