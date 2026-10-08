from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import Case, When
from django.utils import timezone

from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team as TeamModel
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.replay_vision.backend.facade.contracts import ObservationRequestRejected, StartedObservationRequest
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_observation_request import (
    ObservationRequestSource,
    ReplayObservationRequest,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.observation_formatting import format_line, read_output
from products.replay_vision.backend.scanner_access import (
    accessible_observations,
    can_read_targeted_experiment,
    readable_observation_scanner_ids,
)

from ee.hogai.utils.untrusted import as_untrusted_data

if TYPE_CHECKING:
    from posthog.models.team.team import Team

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
    owner_id: int | None,
    session_ids: list[str],
    scanner_id: UUID | None,
    prompt: str | None,
    idempotency_key: str,
    wait_for_session_end: bool = False,
) -> StartedObservationRequest:
    """Scan sessions for a workflow step, with a saved scanner or a plain-language question.

    The step runs as the workflow's owner, so it can only do what that owner could do from the API: read
    recordings, and edit the scanner it names (or the project's scanners, to ask a question). Otherwise
    anyone allowed to edit a workflow could forward recording contents they may not read. Raises
    `ObservationRequestRejected` when the scan can't be requested.
    """
    # Deferred: these reach the temporal package, whose activities import them back while it loads.
    from products.replay_vision.backend.observation_requests import (  # noqa: PLC0415
        IdempotencyKeyConflict,
        InlineScanSpec,
        create_observation_request,
        request_progress,
        step_result,
    )
    from products.replay_vision.backend.scanner_config import scanner_config_error  # noqa: PLC0415
    from products.replay_vision.backend.scanning import MAX_SESSIONS_PER_SCAN  # noqa: PLC0415

    team = TeamModel.objects.select_related("organization").get(id=team_id)
    owner = _workflow_owner(team, owner_id)
    access = UserAccessControl(user=owner, team=team, organization_id=str(team.organization_id))
    if not access.check_access_level_for_resource("session_recording", required_level="viewer"):
        raise ObservationRequestRejected("The workflow's owner can't view session recordings.", "forbidden")
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
        if not access.check_access_level_for_object(scanner, "editor") or not can_read_targeted_experiment(
            access, team.id, scanner
        ):
            raise ObservationRequestRejected("The workflow's owner can't scan with this scanner.", "forbidden")
    else:
        if not access.check_access_level_for_resource("replay_scanner", required_level="editor"):
            raise ObservationRequestRejected(
                "Asking a question needs the workflow's owner to have edit access to the project's scanners.",
                "forbidden",
            )
        config = {"prompt": (prompt or "").strip()}
        error = scanner_config_error(ScannerType.MONITOR, config)
        if error is not None:
            raise ObservationRequestRejected(error, "invalid")
        inline = InlineScanSpec(
            scanner_type=ScannerType.MONITOR, scanner_config=config, model=ScannerModel.GEMINI_3_FLASH_PREVIEW
        )

    try:
        request, created = create_observation_request(
            team=team,
            user=owner,
            source=ObservationRequestSource.WORKFLOW,
            session_ids=sessions,
            scanner=scanner,
            inline=inline,
            idempotency_key=idempotency_key,
            reference="",
            wait_for_session_end=wait_for_session_end,
        )
    except IdempotencyKeyConflict:
        raise ObservationRequestRejected("This step's dispatch key is already used by another request.", "invalid")
    progress = request_progress(request)
    if not progress.settled:
        return StartedObservationRequest(request_id=request.id, status="running", created=created)
    # The step returns these answers now instead of parking, so no wake is owed and the sweep must skip it.
    ReplayObservationRequest.objects.for_team(team.id).filter(id=request.id, completed_at__isnull=True).update(
        completed_at=timezone.now()
    )
    return StartedObservationRequest(
        request_id=request.id, status="completed", created=created, result=step_result(request, progress)
    )


def _workflow_owner(team: TeamModel, owner_id: int | None) -> User:
    owner = User.objects.filter(id=owner_id, is_active=True).first() if owner_id is not None else None
    if (
        owner is None
        or not OrganizationMembership.objects.filter(user=owner, organization_id=team.organization_id).exists()
    ):
        raise ObservationRequestRejected("The workflow has no owner who can run scans.", "forbidden")
    return owner
