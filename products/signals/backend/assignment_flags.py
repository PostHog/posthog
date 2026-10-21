import structlog

from posthog.models.team.team import Team
from posthog.ph_client import feature_enabled_or_false

from products.signals.backend.models import SignalReportAssignmentRevision

logger = structlog.get_logger(__name__)


def _enabled(key: str, team_id: int) -> bool:
    try:
        organization_id = str(Team.objects.values_list("organization_id", flat=True).get(id=team_id))
        return (
            feature_enabled_or_false(
                key,
                organization_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                send_feature_flag_events=False,
            )
            is True
        )
    except Exception:
        logger.exception("signals.assignment.flag_check_failed", team_id=team_id, flag=key)
        return False


def assignment_writer_enabled(team_id: int) -> bool:
    return _enabled("signals-assignment-writer", team_id)


def assignment_side_effects_enabled(team_id: int) -> bool:
    return _enabled("signals-assignment-side-effects", team_id)


def assignment_github_application_enabled(team_id: int) -> bool:
    return _enabled("signals-assignment-github-application", team_id)


def assignment_side_effects_allowed(*, team_id: int, report_id: str, github: bool = False) -> bool:
    # Keep the trial boundary after a writer flag is disabled, including for queued work.
    if not SignalReportAssignmentRevision.objects.for_team(team_id).filter(report_id=report_id).exists():
        return True
    allowed = assignment_side_effects_enabled(team_id) and (
        not github or assignment_github_application_enabled(team_id)
    )
    if not allowed:
        logger.info("signals.assignment.side_effects_disabled", team_id=team_id, report_id=report_id, github=github)
    return allowed
