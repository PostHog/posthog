from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from django.db.models import Case, When
from django.utils import timezone

from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team as TeamModel
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
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
from products.replay_vision.backend.session_limits import MAX_SESSION_ID_LENGTH

from ee.hogai.utils.untrusted import as_untrusted_data

if TYPE_CHECKING:
    from posthog.models.team.team import Team

RejectionKind = Literal["not_found", "consent", "invalid", "forbidden", "rate_limited"]


@dataclass(frozen=True, kw_only=True)
class StartedObservationRequest:
    request_id: UUID
    # "completed" when the session already settled, for example because it was scanned before.
    status: Literal["running", "completed"]
    # False when the idempotency key matched an earlier request and nothing new started.
    created: bool
    # The step's answer, set only when the session was already scanned, so the caller has nothing to wait for.
    result: dict[str, Any] | None = None


# An experiment scan needs a saved scanner, so a workflow step can't run one inline.
INLINE_SCAN_TYPES = (ScannerType.MONITOR, ScannerType.CLASSIFIER, ScannerType.SCORER, ScannerType.SUMMARIZER)
# An experiment scanner samples the experiment's variants evenly, which one session from a workflow trigger can't do.
WORKFLOW_EXPERIMENT_SCANNER_ERROR = (
    "Experiment scanners can't run from a workflow. Choose another scanner or set up the scan in the step."
)


@dataclass(frozen=True, kw_only=True)
class WorkflowInlineScan:
    scanner_type: str
    # The type's `scanner_config`, prompt included, as a saved scanner of that type carries it.
    scanner_config: dict[str, Any]


class ObservationRequestRejected(Exception):
    def __init__(self, detail: str, kind: RejectionKind) -> None:
        super().__init__(detail)
        self.detail = detail
        self.kind = kind


def parse_workflow_scan_setup(setup: Any) -> tuple[UUID | None, WorkflowInlineScan | None]:
    """Read the step's "What should Replay Vision do?" input: a saved scanner, or an inline scan of a type.

    Raises `ObservationRequestRejected` with a message for the step editor when the setup is incomplete.
    """
    # Deferred: scanner_config reaches the temporal package, whose activities import this facade.
    from products.replay_vision.backend.scanner_config import scanner_config_error  # noqa: PLC0415

    if not isinstance(setup, dict) or not isinstance(setup.get("type"), str):
        raise ObservationRequestRejected("Choose what Replay Vision should do.", "invalid")
    if setup["type"] == "scanner":
        try:
            return UUID(str(setup.get("scanner_id"))), None
        except ValueError:
            raise ObservationRequestRejected("Choose a saved scanner.", "invalid")
    if setup["type"] not in INLINE_SCAN_TYPES:
        raise ObservationRequestRejected("Choose what Replay Vision should do.", "invalid")
    config: dict[str, Any] = {"prompt": setup.get("prompt")}
    if setup["type"] == ScannerType.CLASSIFIER:
        config["tags"] = setup.get("tags")
    if setup["type"] == ScannerType.SCORER:
        config["scale"] = setup.get("scale")
    error = scanner_config_error(ScannerType(setup["type"]), config)
    if error is not None:
        raise ObservationRequestRejected(error, "invalid")
    return None, WorkflowInlineScan(scanner_type=setup["type"], scanner_config=config)


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
        .only(
            "id",
            "session_id",
            "scanner_result",
            "created_at",
            "session_started_at",
            "scanner__name",
            "scanner__scanner_type",
        )
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
    hog_flow_id: UUID,
    session_id: str,
    scanner_id: UUID | None,
    inline: WorkflowInlineScan | None,
    idempotency_key: str,
    wait_for_session_end: bool,
    per_workflow_daily_cap: int,
    per_team_daily_cap: int,
) -> StartedObservationRequest:
    """Scan one session for a workflow step, with a saved scanner or an inline scan of any type.

    The step runs as the workflow's owner, so it can only do what that owner could do from the API: read
    recordings, and edit the scanner it names (or the project's scanners, to scan inline). Otherwise
    anyone allowed to edit a workflow could forward recording contents they may not read. The daily caps
    count the workflow's own requests and all workflow requests in the project. Raises
    `ObservationRequestRejected` when the scan can't be requested.
    """
    # Deferred: these reach the temporal package, whose activities import them back while it loads.
    from products.replay_vision.backend.observation_requests import (  # noqa: PLC0415
        IdempotencyKeyConflict,
        InlineScanSpec,
        WorkflowScanCapReached,
        WorkflowScanCaps,
        create_observation_request,
        recording_viewer_access,
        request_progress,
        step_result,
    )
    from products.replay_vision.backend.scanner_config import scanner_config_error  # noqa: PLC0415

    team = TeamModel.objects.select_related("organization").get(id=team_id)
    if team.parent_team_id is not None:
        raise ObservationRequestRejected(
            "Replay Vision scans from workflows are only available in the project's main environment.", "invalid"
        )
    owner = _workflow_owner(team, owner_id)
    access = recording_viewer_access(owner, team)
    if access is None:
        raise ObservationRequestRejected("The workflow's owner can't view session recordings.", "forbidden")
    if not team.organization.is_ai_data_processing_approved:
        raise ObservationRequestRejected(
            "Your organization needs to allow AI analysis before a workflow can run a Replay Vision scan.", "consent"
        )
    session_id = session_id.strip()
    if not session_id:
        raise ObservationRequestRejected("No session to scan. The triggering event has no session ID.", "invalid")
    if len(session_id) > MAX_SESSION_ID_LENGTH:
        raise ObservationRequestRejected(f"Session IDs can be at most {MAX_SESSION_ID_LENGTH} characters.", "invalid")
    if (scanner_id is None) == (inline is None):
        raise ObservationRequestRejected("Choose a saved scanner or set up the scan in the step.", "invalid")

    scanner: ReplayScanner | None = None
    inline_spec: InlineScanSpec | None = None
    if scanner_id is not None:
        scanner = ReplayScanner.objects.filter(team_id=team.id, id=scanner_id).first()
        if scanner is None:
            raise ObservationRequestRejected("No scanner with this ID exists in this project.", "not_found")
        if not _can_scan_with(access, team.id, scanner):
            raise ObservationRequestRejected("The workflow's owner can't scan with this scanner.", "forbidden")
        if scanner.scanner_type == ScannerType.EXPERIMENT:
            raise ObservationRequestRejected(WORKFLOW_EXPERIMENT_SCANNER_ERROR, "invalid")
    elif inline is not None:
        if not access.check_access_level_for_resource("replay_scanner", required_level="editor"):
            raise ObservationRequestRejected(
                "Scanning from the step needs the workflow's owner to have edit access to the project's scanners.",
                "forbidden",
            )
        if inline.scanner_type not in INLINE_SCAN_TYPES:
            raise ObservationRequestRejected("This scan type needs a saved scanner.", "invalid")
        scanner_type = ScannerType(inline.scanner_type)
        error = scanner_config_error(scanner_type, inline.scanner_config)
        if error is not None:
            raise ObservationRequestRejected(error, "invalid")
        inline_spec = InlineScanSpec(
            scanner_type=scanner_type, scanner_config=inline.scanner_config, model=ScannerModel.GEMINI_3_FLASH_PREVIEW
        )

    try:
        request, created = create_observation_request(
            team=team,
            user=owner,
            source=ObservationRequestSource.WORKFLOW,
            session_ids=[session_id],
            scanner=scanner,
            inline=inline_spec,
            idempotency_key=idempotency_key,
            reference=str(hog_flow_id),
            wait_for_session_end=wait_for_session_end,
            workflow_caps=WorkflowScanCaps(per_workflow=per_workflow_daily_cap, per_team=per_team_daily_cap),
        )
    except IdempotencyKeyConflict:
        raise ObservationRequestRejected("This step's dispatch key is already used by another request.", "invalid")
    except WorkflowScanCapReached as reached:
        raise ObservationRequestRejected(_cap_message(reached.scope, reached.cap), "rate_limited")
    progress = request_progress(request)
    if not progress.settled:
        return StartedObservationRequest(request_id=request.id, status="running", created=created)
    # The step returns this answer now instead of parking, so no wake is owed and the sweep must skip it.
    ReplayObservationRequest.objects.for_team(team.id).filter(id=request.id, completed_at__isnull=True).update(
        completed_at=timezone.now()
    )
    return StartedObservationRequest(
        request_id=request.id, status="completed", created=created, result=step_result(request, progress)
    )


def _can_scan_with(access: UserAccessControl, team_id: int, scanner: ReplayScanner) -> bool:
    return bool(access.check_access_level_for_object(scanner, "editor")) and can_read_targeted_experiment(
        access, team_id, scanner
    )


def workflow_scan_editor_error(*, user: User, team: "Team", scanner_id: UUID | None) -> str | None:
    """Why this user may not set up a workflow step's scan, or None. `scanner_id` None means an inline scan.

    The scan runs as the workflow's owner, but whoever saves or live-tests the step chooses the sessions it
    reads, the scanner it uses and where the answers go, so they need the access the owner needs.
    """
    # Deferred: reach the temporal package, whose activities import this facade while it loads.
    from products.replay_vision.backend.observation_requests import recording_viewer_access  # noqa: PLC0415

    access = recording_viewer_access(user, team)
    if access is None:
        return "You need access to session recordings to use the Replay Vision step."
    if scanner_id is None:
        if not access.check_access_level_for_resource("replay_scanner", required_level="editor"):
            return "Setting up a scan in the step needs edit access to the project's scanners."
        return None
    scanner = ReplayScanner.objects.filter(team_id=team.id, id=scanner_id).first()
    if scanner is None:
        return "No scanner with this ID exists in this project."
    if not _can_scan_with(access, team.id, scanner):
        return "You need edit access to this scanner to use it in a workflow."
    if scanner.scanner_type == ScannerType.EXPERIMENT:
        return WORKFLOW_EXPERIMENT_SCANNER_ERROR
    return None


def _cap_message(scope: Literal["workflow", "team"], cap: int) -> str:
    owner = "This workflow" if scope == "workflow" else "This project's workflows"
    if cap == 0:
        return f"Replay Vision scans are paused for {owner.lower()}. Raise the daily limit in project settings."
    return (
        f"{owner} reached the daily limit of {cap} Replay Vision scans. "
        "The event was skipped. Scans resume automatically within 24 hours."
    )


def _workflow_owner(team: TeamModel, owner_id: int | None) -> User:
    owner = User.objects.filter(id=owner_id, is_active=True).first() if owner_id is not None else None
    if (
        owner is None
        or not OrganizationMembership.objects.filter(user=owner, organization_id=team.organization_id).exists()
    ):
        raise ObservationRequestRejected("The workflow has no owner who can run scans.", "forbidden")
    return owner


def signal_emitting_scanner_ids(team_id: int, scanner_ids: list[str]) -> set[str]:
    return {
        str(scanner_id)
        for scanner_id in ReplayScanner.objects.filter(
            team_id=team_id, id__in=scanner_ids, enabled=True, emits_signals=True
        ).values_list("id", flat=True)
    }
