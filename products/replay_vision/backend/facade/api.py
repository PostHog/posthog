from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import Case, When

from posthog.models.team.team import Team as TeamModel

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.replay_vision.backend.facade.contracts import ObservationRequestRejected, StartedObservationRequest
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_observation_request import ObservationRequestSource
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.observation_formatting import format_line, read_output
from products.replay_vision.backend.scanner_access import accessible_observations, readable_observation_scanner_ids

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

    queryset = (
        accessible_observations(
            access,
            team.id,
            ReplayObservation.objects.filter(
                team_id=team.id,
                scanner_id__in=readable_scanner_ids,
                session_id__in=session_ids,
                status=ObservationStatus.SUCCEEDED,
            ),
        )
        .select_related("scanner")
        .only("id", "session_id", "scanner_result", "created_at", "scanner__name", "scanner__scanner_type")
    )
    if prefer_summarizer:
        queryset = queryset.order_by(
            Case(
                When(scanner__scanner_type__in=(ScannerType.SUMMARIZER, ScannerType.EXPERIMENT), then=0),
                default=1,
            ),
            "-created_at",
        )
    else:
        queryset = queryset.order_by("-created_at")

    lines: list[str] = []
    for obs in queryset[:limit]:
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


def start_workflow_observation_request(
    *,
    team_id: int,
    session_ids: list[str],
    scanner_id: UUID | None,
    prompt: str | None,
    idempotency_key: str,
) -> StartedObservationRequest:
    """Scan sessions for a workflow step, with a saved scanner or a plain-language question.

    No user stands behind the call, so access is the workflow's: the step can only name sessions and
    scanners in its own project. Raises `ObservationRequestRejected` when the scan can't be requested.
    """
    # Deferred: these reach the temporal package, whose activities import them back while it loads.
    from products.replay_vision.backend.observation_requests import (  # noqa: PLC0415
        InlineScanSpec,
        create_observation_request,
        observation_requests_enabled,
        request_progress,
    )
    from products.replay_vision.backend.scanner_config import scanner_config_error  # noqa: PLC0415
    from products.replay_vision.backend.scanning import MAX_SESSIONS_PER_SCAN  # noqa: PLC0415

    team = TeamModel.objects.select_related("organization").get(id=team_id)
    if not observation_requests_enabled(team, f"team-{team.id}"):
        raise ObservationRequestRejected("Replay vision scans from workflows aren't available yet.", "disabled")
    if not team.organization.is_ai_data_processing_approved:
        raise ObservationRequestRejected(
            "Your organization needs to allow AI analysis before a workflow can run a Replay vision scan.", "consent"
        )
    sessions = list(dict.fromkeys(s for s in session_ids if s))
    if not sessions:
        raise ObservationRequestRejected("No session to scan. The triggering event has no session id.", "invalid")
    if len(sessions) > MAX_SESSIONS_PER_SCAN:
        raise ObservationRequestRejected(f"At most {MAX_SESSIONS_PER_SCAN} sessions can be scanned at once.", "invalid")

    scanner: ReplayScanner | None = None
    inline: InlineScanSpec | None = None
    if scanner_id is not None:
        scanner = ReplayScanner.objects.filter(team_id=team.id, id=scanner_id).first()
        if scanner is None:
            raise ObservationRequestRejected("No scanner with this id exists in this project.", "not_found")
    else:
        config = {"prompt": (prompt or "").strip()}
        error = scanner_config_error(ScannerType.MONITOR, config)
        if error is not None:
            raise ObservationRequestRejected(error, "invalid")
        inline = InlineScanSpec(
            scanner_type=ScannerType.MONITOR, scanner_config=config, model=ScannerModel.GEMINI_3_FLASH_PREVIEW
        )

    request, created = create_observation_request(
        team=team,
        user=None,
        source=ObservationRequestSource.WORKFLOW,
        session_ids=sessions,
        scanner=scanner,
        inline=inline,
        idempotency_key=idempotency_key,
        reference="",
    )
    return StartedObservationRequest(
        request_id=request.id,
        status="completed" if request_progress(request).settled else "running",
        created=created,
    )
