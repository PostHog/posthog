import uuid
from typing import TYPE_CHECKING

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType
from products.replay_vision.backend.observation_formatting import format_line, read_output
from products.replay_vision.backend.scanner_access import (
    accessible_observations,
    readable_observation_scanner_ids,
    scanners_for_reading_observations,
)

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
    the user can read no scanners, or none of the sessions were observed. `None` (not an empty string) is the "no Vision enrichment" signal the caller degrades on.

    Access: an observation inherits its scanner's RBAC and, for an experiment scanner, the access to its
    targeted experiment — so the scanner set is filtered by the user's access level (never `team_id` alone)
    and each row is gated against the experiment in its snapshot. Otherwise output from scanners the user
    can't read, or from experiments they can't view, would leak. This mirrors `SearchReplayVisionObservationsTool`;
    the session-existence tradeoff it documents applies here too.

    The observations summarize the *whole session* (which may span many pages), so the caller must present
    this as session-level color for visitors who touched the page, not page-specific ground truth.

    Runs synchronous DB access; call it from an async tool via `database_sync_to_async`.
    """
    if not session_ids:
        return None
    access = UserAccessControl(user=user, team=team, organization_id=str(team.organization_id))
    readable_scanner_ids = readable_observation_scanner_ids(access, team.id)
    if not readable_scanner_ids:
        return None

    def newest_first(scanner_ids: list[uuid.UUID], count: int) -> list[ReplayObservation]:
        return list(
            accessible_observations(
                access,
                team.id,
                ReplayObservation.objects.filter(
                    team_id=team.id,
                    scanner_id__in=scanner_ids,
                    session_id__in=session_ids,
                    status=ObservationStatus.SUCCEEDED,
                ),
            )
            .select_related("scanner")
            .only("id", "session_id", "scanner_result", "created_at", "scanner__name", "scanner__scanner_type")
            .order_by("-created_at")[:count]
        )

    if prefer_summarizer:
        # Two plain created_at reads instead of one sort on a CASE over scanner_type: no index serves the
        # CASE, so Postgres joined and sorted every matching row before it applied the limit.
        preferred_ids = set(
            scanners_for_reading_observations(team.id)
            .filter(id__in=readable_scanner_ids, scanner_type__in=(ScannerType.SUMMARIZER, ScannerType.EXPERIMENT))
            .values_list("id", flat=True)
        )
        other_ids = [scanner_id for scanner_id in readable_scanner_ids if scanner_id not in preferred_ids]
        observations = newest_first(list(preferred_ids), limit) if preferred_ids else []
        if other_ids and len(observations) < limit:
            observations += newest_first(other_ids, limit - len(observations))
    else:
        observations = newest_first(readable_scanner_ids, limit)

    lines: list[str] = []
    for obs in observations:
        output = read_output(obs)
        if output is None:
            continue
        lines.append(format_line(obs, output, show_scanner=True))

    if not lines:
        return None

    return as_untrusted_data("observations", lines)


def has_signal_emitting_scanner(team_id: int) -> bool:
    """Whether any of the team's scanners feeds findings into the Signals inbox.

    Replay Vision authorizes signal emission per scanner (`emits_signals`) instead of writing a
    `SignalSourceConfig` row, so callers asking "is this source on?" can't answer it from the
    signals tables alone. See `SignalSourceConfig.is_source_enabled`.
    """
    return ReplayScanner.objects.filter(team_id=team_id, enabled=True, emits_signals=True).exists()
