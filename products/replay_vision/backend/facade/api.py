from typing import TYPE_CHECKING

from django.db.models import Case, When

from posthog.rbac.user_access_control import UserAccessControl

from products.replay_vision.backend.feature_flag import is_replay_vision_enabled
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType
from products.replay_vision.backend.observation_formatting import _format_line, _read_output

from ee.hogai.utils.untrusted import as_untrusted_data

if TYPE_CHECKING:
    from posthog.models.team.team import Team
    from posthog.models.user import User

_MAX_PAGE_OBSERVATIONS = 30


def fetch_page_session_observations(
    *,
    team: "Team",
    user: "User",
    session_ids: list[str],
    prefer_summarizer: bool = True,
    limit: int = _MAX_PAGE_OBSERVATIONS,
) -> str | None:
    """Replay Vision observations for the given sessions, already fenced and ready to embed in a Max report.

    Returns an `<observations>` block wrapped by the shared indirect-prompt-injection fence, or `None` when
    Replay Vision is disabled for the project, the user can read no scanners, or none of the sessions were
    observed. `None` (not an empty string) is the "no Vision enrichment" signal the caller degrades on.

    Access: an observation inherits its scanner's RBAC, so the scanner set is filtered by the user's access
    level — never `team_id` alone — otherwise output from scanners the user can't read would leak. This
    mirrors `SearchReplayVisionObservationsTool`; the session-existence tradeoff it documents applies here too.

    The observations summarize the *whole session* (which may span many pages), so the caller must present
    this as session-level color for visitors who touched the page, not page-specific ground truth.

    Runs synchronous DB access; call it from an async tool via `database_sync_to_async`.
    """
    if not session_ids:
        return None
    if not is_replay_vision_enabled(user, team):
        return None

    readable_scanner_ids = [
        str(sid)
        for sid in UserAccessControl(user=user, team=team, organization_id=str(team.organization_id))
        .filter_queryset_by_access_level(ReplayScanner.objects.filter(team_id=team.id))
        .values_list("id", flat=True)
    ]
    if not readable_scanner_ids:
        return None

    queryset = (
        ReplayObservation.objects.filter(
            team_id=team.id,
            scanner_id__in=readable_scanner_ids,
            session_id__in=session_ids,
            status=ObservationStatus.SUCCEEDED,
        )
        .select_related("scanner")
        .only("id", "session_id", "scanner_result", "created_at", "scanner__name", "scanner__scanner_type")
    )
    if prefer_summarizer:
        queryset = queryset.order_by(
            Case(When(scanner__scanner_type=ScannerType.SUMMARIZER, then=0), default=1), "-created_at"
        )
    else:
        queryset = queryset.order_by("-created_at")

    lines: list[str] = []
    for obs in queryset[:limit]:
        output = _read_output(obs)
        if output is None:
            continue
        lines.append(_format_line(obs, output, show_scanner=True))

    if not lines:
        return None

    return as_untrusted_data("observations", lines)
