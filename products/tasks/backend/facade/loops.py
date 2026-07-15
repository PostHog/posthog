"""
Facade API for Loops — the data surface DRF views for `products/tasks/backend/presentation/views/loops.py`
call into. See `products/tasks/docs/LOOPS.md` for the full spec.

Responsibilities:
- Accept ids / primitives as input, enforce visibility and permission rules.
- Call into `Loop` / `LoopTrigger` / `TaskRun` models, `loop_service` (Temporal schedules) and
  `loop_runs` (fire + trigger-context rendering).
- Convert Django models to DTOs before returning — never return ORM instances.

Permission model (see LOOPS.md "Access control"):
- Personal loops are owner-only for everything (view, edit, fire, run history).
- Team loops are viewable/fireable by any team member. Identity-bearing config
  (visibility, instructions, runtime_adapter, model, reasoning_effort, repositories,
  sandbox_environment, connectors, behaviors, triggers) is mutable only by the owner.
  Non-identity fields (name, description, notifications, enable/pause) are mutable by
  any member.
- Project admins may always pause or delete a loop, regardless of visibility or ownership
  (the kill switch when an owner is unavailable).
"""

import json
import base64
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import Q, QuerySet

from pydantic import Field
from pydantic.dataclasses import dataclass

from posthog.models import User
from posthog.models.file_system.file_system import FileSystem
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership

from products.mcp_store.backend.facade.api import get_active_installations
from products.tasks.backend import loop_service
from products.tasks.backend.logic.services import loop_runs
from products.tasks.backend.loop_lifecycle import pause_loops_for_deactivated_user, pause_loops_referencing_integrations
from products.tasks.backend.models import Loop, LoopTrigger, SandboxEnvironment, Task, TaskRun

# --- Enum re-exports ---
# Value types (not ORM models), safe for presentation to import for serializer choices.
LoopVisibility = Loop.Visibility
LoopOverlapPolicy = Loop.OverlapPolicy
LoopTriggerType = LoopTrigger.TriggerType
LoopScheduleSyncStatus = LoopTrigger.ScheduleSyncStatus

LoopFireResult = loop_runs.LoopFireResult

DEFAULT_MAX_FIX_ITERATIONS = 3
MAX_FIX_ITERATIONS_CEILING = 10
DEFAULT_POSTHOG_MCP_SCOPES = "read_only"
POSTHOG_MCP_SCOPES_CHOICES = ("read_only", "full")
NOTIFICATION_CHANNELS = ("push", "email", "slack")
NOTIFICATION_EVENTS = ("run_completed", "run_failed", "pr_created", "needs_attention")
ALLOWED_GITHUB_TRIGGER_EVENTS = ("issues", "issue_comment", "pull_request", "push")
MAX_LOOP_REPOSITORIES = 1

# Abuse/DoS ceilings. Each schedule trigger mints one Temporal Schedule and each loop can fire
# LOOP_RATE_CAP_PER_DAY times, so these two caps together bound a team's total schedule count
# (MAX_LOOPS_PER_TEAM * MAX_TRIGGERS_PER_LOOP) and daily run volume. Keep them generous enough
# for real use but low enough that a runaway script or leaked credential can't overwhelm the
# scheduler. Raising them is a deliberate, per-request-to-support decision.
MAX_LOOPS_PER_TEAM = 100
MAX_TRIGGERS_PER_LOOP = 25

DEFAULT_LOOP_RUN_PAGE_SIZE = 50
MAX_LOOP_RUN_PAGE_SIZE = 100

# Identity-bearing Loop fields: mutable only by the owner on a team loop (see module docstring).
# `visibility` is included because flipping personal<->team changes who can see/control the loop.
IDENTITY_FIELDS: frozenset[str] = frozenset(
    {
        "visibility",
        "instructions",
        "runtime_adapter",
        "model",
        "reasoning_effort",
        "repositories",
        "sandbox_environment_id",
        "behaviors",
        "connectors",
        "context_target",
        "triggers",
    }
)
_PAUSE_FIELD = "enabled"

# Desktop file-system node types the loop's context attachment references (see LOOPS.md). A context
# is a `folder`; a maintained living dashboard is a `dashboard` (canvas). Both live on the `desktop`
# surface.
DESKTOP_SURFACE = "desktop"
DESKTOP_FOLDER_TYPE = "folder"
DESKTOP_CANVAS_TYPE = "dashboard"


class LoopPermissionError(Exception):
    """Raised when a visible loop write is rejected by the access-control rules in this module.

    Callers (the view layer) should catch this and translate to a 403.
    """


class LoopLimitError(Exception):
    """Raised when a write is rejected by an abuse/safety ceiling (loops per team, triggers per
    loop). Carries a stable machine-readable `code` and the `limit` that was hit so the view can
    return a structured response the frontend can articulate to the user, distinct from a
    generic validation error. Callers translate to a 429."""

    def __init__(self, code: str, limit: int, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.limit = limit
        self.detail = detail


# --- Contract types ---
# Framework-free frozen dataclasses, mirroring the shape of `products.tasks.backend.facade.contracts`
# but kept local to this module since Loops does not yet have a place in `contracts.py`.


@dataclass(frozen=True)
class LoopRepositoryEntryDTO:
    github_integration_id: int
    full_name: str


@dataclass(frozen=True)
class LoopBehaviorsDTO:
    create_prs: bool = False
    watch_ci: bool = False
    fix_review_comments: bool = False
    max_fix_iterations: int = DEFAULT_MAX_FIX_ITERATIONS


@dataclass(frozen=True)
class LoopConnectorsDTO:
    mcp_installation_ids: list[str] = Field(default_factory=list)
    posthog_mcp_scopes: str = DEFAULT_POSTHOG_MCP_SCOPES


@dataclass(frozen=True)
class LoopNotificationChannelDTO:
    enabled: bool = False
    events: list[str] = Field(default_factory=list)
    params: dict = Field(default_factory=dict)


@dataclass(frozen=True)
class LoopNotificationsDTO:
    push: LoopNotificationChannelDTO = Field(default_factory=LoopNotificationChannelDTO)
    email: LoopNotificationChannelDTO = Field(default_factory=LoopNotificationChannelDTO)
    slack: LoopNotificationChannelDTO = Field(default_factory=LoopNotificationChannelDTO)


@dataclass(frozen=True)
class LoopContextOutputsDTO:
    """What a context-attached loop maintains each run (see LOOPS.md "Contexts")."""

    post_to_feed: bool = False
    update_context: bool = False
    canvas_id: str | None = None


@dataclass(frozen=True)
class LoopContextTargetDTO:
    """The context (a "#channel" / desktop folder) a loop is attached to, plus what it maintains."""

    folder_id: str
    name: str
    outputs: LoopContextOutputsDTO = Field(default_factory=LoopContextOutputsDTO)


@dataclass(frozen=True)
class LoopTriggerDTO:
    """A single loop trigger. `config` shape depends on `type` — see LOOPS.md `LoopTrigger`."""

    id: UUID
    loop_id: UUID
    type: str
    enabled: bool
    config: dict
    schedule_sync_status: str | None
    last_fired_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class LoopDTO:
    id: UUID
    team_id: int
    created_by_id: int | None
    name: str
    description: str
    visibility: str
    instructions: str
    runtime_adapter: str
    model: str
    reasoning_effort: str | None
    repositories: list[LoopRepositoryEntryDTO]
    sandbox_environment_id: UUID | None
    enabled: bool
    overlap_policy: str
    behaviors: LoopBehaviorsDTO
    connectors: LoopConnectorsDTO
    notifications: LoopNotificationsDTO
    internal: bool
    origin_product: str
    last_run_at: datetime | None
    last_run_status: str | None
    last_error: str | None
    consecutive_failures: int
    created_at: datetime
    updated_at: datetime
    context_target: LoopContextTargetDTO | None = None
    triggers: list[LoopTriggerDTO] = Field(default_factory=list)


@dataclass(frozen=True)
class LoopRunDTO:
    id: UUID
    task_id: UUID
    loop_trigger_id: UUID | None
    status: str
    environment: str
    branch: str | None
    error_message: str | None
    output: dict | None
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class LoopRunPageDTO:
    runs: list[LoopRunDTO] = Field(default_factory=list)
    next_cursor: str | None = None


@dataclass(frozen=True)
class LoopPreviewDTO:
    instructions: str
    trigger_type: str
    trigger_context: str


# --- Mapping helpers ---


def _behaviors_dto(raw: dict | None) -> LoopBehaviorsDTO:
    raw = raw or {}
    return LoopBehaviorsDTO(
        create_prs=bool(raw.get("create_prs", False)),
        watch_ci=bool(raw.get("watch_ci", False)),
        fix_review_comments=bool(raw.get("fix_review_comments", False)),
        max_fix_iterations=int(raw.get("max_fix_iterations", DEFAULT_MAX_FIX_ITERATIONS)),
    )


def _notification_channel_dto(raw: dict | None) -> LoopNotificationChannelDTO:
    raw = raw or {}
    events = raw.get("events")
    return LoopNotificationChannelDTO(
        enabled=bool(raw.get("enabled", False)),
        events=list(events) if isinstance(events, list) else [],
        params=dict(raw.get("params") or {}),
    )


def _notifications_dto(raw: dict | None) -> LoopNotificationsDTO:
    raw = raw or {}
    return LoopNotificationsDTO(
        push=_notification_channel_dto(raw.get("push")),
        email=_notification_channel_dto(raw.get("email")),
        slack=_notification_channel_dto(raw.get("slack")),
    )


def _connectors_dto(raw: dict | None) -> LoopConnectorsDTO:
    raw = raw or {}
    mcp_installation_ids = raw.get("mcp_installation_ids")
    return LoopConnectorsDTO(
        mcp_installation_ids=list(mcp_installation_ids) if isinstance(mcp_installation_ids, list) else [],
        posthog_mcp_scopes=raw.get("posthog_mcp_scopes") or DEFAULT_POSTHOG_MCP_SCOPES,
    )


def _context_target_dto(raw: dict | None) -> LoopContextTargetDTO | None:
    raw = raw or {}
    folder_id = raw.get("folder_id")
    name = raw.get("name")
    if not folder_id or not name:
        return None
    outputs = raw.get("outputs") or {}
    canvas_id = outputs.get("canvas_id")
    return LoopContextTargetDTO(
        folder_id=str(folder_id),
        name=str(name),
        outputs=LoopContextOutputsDTO(
            post_to_feed=bool(outputs.get("post_to_feed", False)),
            update_context=bool(outputs.get("update_context", False)),
            canvas_id=str(canvas_id) if canvas_id else None,
        ),
    )


def _repository_dtos(raw: list | None) -> list[LoopRepositoryEntryDTO]:
    entries = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        github_integration_id = entry.get("github_integration_id")
        full_name = entry.get("full_name")
        if github_integration_id is None or not full_name:
            continue
        entries.append(LoopRepositoryEntryDTO(github_integration_id=int(github_integration_id), full_name=full_name))
    return entries


def _trigger_to_dto(trigger: LoopTrigger) -> LoopTriggerDTO:
    return LoopTriggerDTO(
        id=trigger.id,
        loop_id=trigger.loop_id,
        type=trigger.type,
        enabled=trigger.enabled,
        config=trigger.config or {},
        schedule_sync_status=trigger.schedule_sync_status,
        last_fired_at=trigger.last_fired_at,
        created_at=trigger.created_at,
        updated_at=trigger.updated_at,
    )


def _loop_to_dto(loop: Loop) -> LoopDTO:
    triggers = sorted(loop.triggers.all(), key=lambda trigger: trigger.created_at)
    return LoopDTO(
        id=loop.id,
        team_id=loop.team_id,
        created_by_id=loop.created_by_id,
        name=loop.name,
        description=loop.description,
        visibility=loop.visibility,
        instructions=loop.instructions,
        runtime_adapter=loop.runtime_adapter,
        model=loop.model,
        reasoning_effort=loop.reasoning_effort,
        repositories=_repository_dtos(loop.repositories),
        sandbox_environment_id=loop.sandbox_environment_id,
        enabled=loop.enabled,
        overlap_policy=loop.overlap_policy,
        behaviors=_behaviors_dto(loop.behaviors),
        connectors=_connectors_dto(loop.connectors),
        notifications=_notifications_dto(loop.notifications),
        internal=loop.internal,
        origin_product=loop.origin_product,
        last_run_at=loop.last_run_at,
        last_run_status=loop.last_run_status,
        last_error=loop.last_error,
        consecutive_failures=loop.consecutive_failures,
        created_at=loop.created_at,
        updated_at=loop.updated_at,
        context_target=_context_target_dto(loop.context_target),
        triggers=[_trigger_to_dto(trigger) for trigger in triggers],
    )


def _parse_uuid(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _task_run_to_loop_run_dto(run: TaskRun) -> LoopRunDTO:
    state = run.state or {}
    return LoopRunDTO(
        id=run.id,
        task_id=run.task_id,
        loop_trigger_id=_parse_uuid(state.get("loop_trigger_id")),
        status=run.status,
        environment=run.environment,
        branch=run.branch,
        error_message=run.error_message,
        output=run.output,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


# --- Visibility / permission helpers ---


def _visible_loop_queryset(team_id: int, user_id: int | None) -> QuerySet[Loop]:
    # `internal=False`: loops created by a backend flow for internal use are attached to the
    # team/owner but never surfaced through the user-facing API (mirrors Task.internal).
    visibility_q = Q(visibility=Loop.Visibility.TEAM)
    if user_id is not None:
        visibility_q |= Q(created_by_id=user_id)
    return Loop.objects.filter(team_id=team_id, deleted=False, internal=False).filter(visibility_q)


def _is_owner(loop: Loop, user: User | None) -> bool:
    return user is not None and loop.created_by_id == user.id


def _is_team_admin(loop: Loop, user: User | None) -> bool:
    if user is None:
        return False
    return OrganizationMembership.objects.filter(
        user_id=user.id,
        organization_id=loop.team.organization_id,
        level__gte=OrganizationMembership.Level.ADMIN,
    ).exists()


def _fetch_loop_for_write(loop_id: str | UUID, team_id: int, user: User | None) -> Loop | None:
    """Fetch a loop for `update_loop`/`soft_delete_loop`.

    Broader than `_visible_loop_queryset`: an admin must be able to reach (in order to pause or
    delete) a personal loop they don't own, since that's the documented kill switch. `None` here
    means "genuinely unreachable" (wrong team, deleted, or a personal loop belonging to someone
    else with no admin override) and the caller should treat it as 404. Reaching a personal loop
    as a non-owner admin still only grants pause/delete, enforced by `_authorize_update` and
    `soft_delete_loop`'s own owner-or-admin check, not general edit rights.
    """
    user_id = getattr(user, "id", None)
    # `internal=False`: internal loops are managed by their backend flow, never through the
    # user-facing write/fire/delete API.
    loop = (
        Loop.objects.filter(team_id=team_id, deleted=False, internal=False, pk=loop_id).select_related("team").first()
    )
    if loop is None:
        return None
    if loop.visibility == Loop.Visibility.TEAM or _is_owner(loop, user):
        return loop
    if user_id is not None and _is_team_admin(loop, user):
        return loop
    return None


def _authorize_update(loop: Loop, user: User | None, validated_data: dict) -> None:
    if _is_owner(loop, user):
        return

    if loop.visibility == Loop.Visibility.PERSONAL:
        if set(validated_data) <= {_PAUSE_FIELD} and _is_team_admin(loop, user):
            return
        raise LoopPermissionError("Only the owner may edit a personal loop.")

    # Team loop: any member may edit non-identity fields; identity-bearing fields
    # (see IDENTITY_FIELDS) require ownership or an explicit takeover, which isn't
    # wired as a separate API surface yet.
    if any(field_name in IDENTITY_FIELDS for field_name in validated_data):
        raise LoopPermissionError(
            "Only the loop owner may change identity-bearing configuration (instructions, "
            "repositories, connectors, behaviors, model config, or triggers)."
        )


# --- Cross-model validation helpers exposed to the write serializer ---


def sandbox_environment_queryset() -> QuerySet[SandboxEnvironment]:
    """Live `SandboxEnvironment` queryset for the loop write serializer's FK field.

    Kept here so presentation never imports tasks models directly; team scoping is applied
    by the serializer's `TeamScopedPrimaryKeyRelatedField`.
    """
    return SandboxEnvironment.objects.all()


def active_mcp_installation_ids(team_id: int, owner_id: int | None) -> set[str]:
    """Active MCP Store installation ids for the loop owner, for connectors validation.

    Connectors are identity-bearing (owner-only to edit), so the acting user is always the
    owner whenever this matters — see `_authorize_update`.
    """
    if owner_id is None:
        return set()
    return {installation.id for installation in get_active_installations(team_id, owner_id)}


def github_integration_ids_for_team(team_id: int, integration_ids: Iterable[int]) -> set[int]:
    return set(
        Integration.objects.filter(team_id=team_id, kind="github", id__in=list(integration_ids)).values_list(
            "id", flat=True
        )
    )


def _desktop_node_exists(team_id: int, node_id: str, *, node_type: str) -> bool:
    parsed = _parse_uuid(node_id)
    if parsed is None:
        return False
    return FileSystem.objects.filter(team_id=team_id, surface=DESKTOP_SURFACE, type=node_type, id=parsed).exists()


def desktop_folder_exists(team_id: int, folder_id: str) -> bool:
    """Whether `folder_id` is a desktop context folder in this team (loop context-attach validation)."""
    return _desktop_node_exists(team_id, folder_id, node_type=DESKTOP_FOLDER_TYPE)


def desktop_canvas_exists(team_id: int, canvas_id: str) -> bool:
    """Whether `canvas_id` is a desktop canvas in this team (loop context-attach validation)."""
    return _desktop_node_exists(team_id, canvas_id, node_type=DESKTOP_CANVAS_TYPE)


# --- CRUD ---


def list_loops(team_id: int, user: User | None) -> list[LoopDTO]:
    user_id = getattr(user, "id", None)
    loops = (
        _visible_loop_queryset(team_id, user_id)
        .select_related("sandbox_environment")
        .prefetch_related("triggers")
        .order_by("-created_at")
    )
    return [_loop_to_dto(loop) for loop in loops]


def visible_loop_ids(team_id: int, user: User | None) -> set[str]:
    """Ids of loops the user may see, as strings. For callers outside request/team scope
    (e.g. the activity-log viewset restricting `Loop`-scoped rows): uses `for_team` explicitly
    so it never depends on ambient team context, unlike `list_loops`/`_visible_loop_queryset`."""
    user_id = getattr(user, "id", None)
    visibility_q = Q(visibility=Loop.Visibility.TEAM)
    if user_id is not None:
        visibility_q |= Q(created_by_id=user_id)
    loops = Loop.objects.for_team(team_id, canonical=True).filter(deleted=False, internal=False).filter(visibility_q)
    return {str(loop_id) for loop_id in loops.values_list("id", flat=True)}


def get_loop(loop_id: str | UUID, team_id: int, user: User | None) -> LoopDTO | None:
    user_id = getattr(user, "id", None)
    loop = _visible_loop_queryset(team_id, user_id).prefetch_related("triggers").filter(pk=loop_id).first()
    return _loop_to_dto(loop) if loop is not None else None


def create_loop(team_id: int, user: User | None, validated_data: dict) -> LoopDTO:
    data = dict(validated_data)
    trigger_payloads = data.pop("triggers", None) or []

    if len(trigger_payloads) > MAX_TRIGGERS_PER_LOOP:
        raise LoopLimitError(
            code="max_triggers_per_loop",
            limit=MAX_TRIGGERS_PER_LOOP,
            detail=f"A loop can have at most {MAX_TRIGGERS_PER_LOOP} triggers.",
        )

    existing_loops = Loop.objects.for_team(team_id, canonical=True).filter(deleted=False).count()
    if existing_loops >= MAX_LOOPS_PER_TEAM:
        raise LoopLimitError(
            code="max_loops_per_team",
            limit=MAX_LOOPS_PER_TEAM,
            detail=(
                f"This project has reached the limit of {MAX_LOOPS_PER_TEAM} loops. "
                "Delete a loop to make room, or contact support to raise the limit."
            ),
        )

    with transaction.atomic():
        loop = Loop.objects.create(
            team_id=team_id,
            created_by_id=getattr(user, "id", None),
            name=data["name"],
            description=data.get("description", ""),
            visibility=data.get("visibility", Loop.Visibility.PERSONAL),
            instructions=data["instructions"],
            runtime_adapter=data["runtime_adapter"],
            model=data["model"],
            reasoning_effort=data.get("reasoning_effort"),
            repositories=data.get("repositories", []),
            sandbox_environment_id=data.get("sandbox_environment_id"),
            enabled=data.get("enabled", True),
            overlap_policy=data.get("overlap_policy", Loop.OverlapPolicy.SKIP),
            behaviors=data.get("behaviors") or {},
            connectors=data.get("connectors") or {},
            notifications=data.get("notifications") or {},
            context_target=data.get("context_target") or {},
            # Backend-only: the API write serializer never carries these, so loops made through
            # the public API are always user-facing and attributed to `user_created`.
            internal=data.get("internal", False),
            origin_product=data.get("origin_product", Task.OriginProduct.USER_CREATED),
        )
        created_triggers = [
            LoopTrigger.objects.create(
                team_id=loop.team_id,
                loop=loop,
                type=payload["type"],
                enabled=payload.get("enabled", True),
                config=payload.get("config") or {},
                schedule_sync_status=LoopTrigger.ScheduleSyncStatus.PENDING,
            )
            for payload in trigger_payloads
        ]

    for trigger in created_triggers:
        loop_service.sync_loop_trigger_schedule(trigger)

    loop.refresh_from_db()
    return _loop_to_dto(loop)


def update_loop(loop_id: str | UUID, team_id: int, user: User | None, validated_data: dict) -> LoopDTO | None:
    """Partially update a loop reachable by the user (see `_fetch_loop_for_write`). Raises
    `LoopPermissionError` if the user may reach the loop but not make this particular write.
    Returns `None` if not found/reachable."""
    loop = _fetch_loop_for_write(loop_id, team_id, user)
    if loop is None:
        return None

    _authorize_update(loop, user, validated_data)

    data = dict(validated_data)
    trigger_payloads = data.pop("triggers", None)
    # Detaching from a context sends `context_target: null`; the column is NOT NULL, so store {}.
    if "context_target" in data and data["context_target"] is None:
        data["context_target"] = {}

    with transaction.atomic():
        for field_name, value in data.items():
            setattr(loop, field_name, value)
        loop.save()

    if trigger_payloads is not None:
        _sync_triggers(loop, trigger_payloads)

    loop.refresh_from_db()
    return _loop_to_dto(loop)


def soft_delete_loop(loop_id: str | UUID, team_id: int, user: User | None) -> bool:
    loop = _fetch_loop_for_write(loop_id, team_id, user)
    if loop is None:
        return False

    if not (_is_owner(loop, user) or _is_team_admin(loop, user)):
        raise LoopPermissionError("Only the owner or a project admin may delete a loop.")

    loop.deleted = True
    loop.save(update_fields=["deleted", "updated_at"])
    loop_service.pause_loop_schedules(loop)
    return True


def _sync_triggers(loop: Loop, trigger_payloads: list[dict]) -> None:
    """Id-stable nested trigger sync for an existing loop (see LOOPS.md "Lifecycle and
    reconciliation"). Loop creation handles its (necessarily all-new) triggers inline in
    `create_loop` instead of through here.

    Matches incoming trigger payloads by `id`: updates matched rows in place, creates rows with
    no matching `id`, and deletes existing rows absent from `trigger_payloads`. Schedule sync
    happens after the DB transaction commits; schedule deletion happens before the DB row is
    deleted, so a crash between the two leaves an orphaned-but-recoverable state for the
    reconciliation sweep rather than a dangling Temporal schedule.
    """
    if len(trigger_payloads) > MAX_TRIGGERS_PER_LOOP:
        raise LoopLimitError(
            code="max_triggers_per_loop",
            limit=MAX_TRIGGERS_PER_LOOP,
            detail=f"A loop can have at most {MAX_TRIGGERS_PER_LOOP} triggers.",
        )

    existing_by_id: dict[UUID, LoopTrigger] = {trigger.id: trigger for trigger in loop.triggers.all()}
    seen_ids: set[UUID] = set()
    to_sync: list[LoopTrigger] = []

    with transaction.atomic():
        for payload in trigger_payloads:
            trigger_id = payload.get("id")
            existing = existing_by_id.get(trigger_id) if trigger_id else None
            if existing is not None:
                existing.type = payload["type"]
                existing.enabled = payload.get("enabled", True)
                existing.config = payload.get("config") or {}
                existing.schedule_sync_status = LoopTrigger.ScheduleSyncStatus.PENDING
                existing.save()
                seen_ids.add(existing.id)
                to_sync.append(existing)
            else:
                created = LoopTrigger.objects.create(
                    team_id=loop.team_id,
                    loop=loop,
                    type=payload["type"],
                    enabled=payload.get("enabled", True),
                    config=payload.get("config") or {},
                    schedule_sync_status=LoopTrigger.ScheduleSyncStatus.PENDING,
                )
                seen_ids.add(created.id)
                to_sync.append(created)

        stale = [trigger for trigger_id, trigger in existing_by_id.items() if trigger_id not in seen_ids]

    for trigger in stale:
        loop_service.delete_loop_trigger_schedule(trigger)
        trigger.delete()

    for trigger in to_sync:
        loop_service.sync_loop_trigger_schedule(trigger)


# --- Firing ---


def fire_loop_manual(
    loop_id: str | UUID, team_id: int, user: User | None, idempotency_key: str | None = None
) -> LoopFireResult | None:
    """Manual fire from the UI (`loops/:id/run/`). Visibility (`_visible_loop_queryset`) already
    encodes who may fire a loop manually: owner-only for personal, any member for team."""
    user_id = getattr(user, "id", None)
    loop = _visible_loop_queryset(team_id, user_id).filter(pk=loop_id).first()
    if loop is None:
        return None

    fire_key = idempotency_key or f"manual-{uuid4().hex}"
    trigger_context = loop_runs.render_trigger_context("manual", None, loop)
    return loop_runs.fire_loop(loop=loop, trigger=None, fire_key=fire_key, trigger_context=trigger_context, actor=user)


def fire_loop_api(
    loop_id: str | UUID, team_id: int, payload: dict | None, idempotency_key: str | None = None
) -> LoopFireResult | None:
    """External fire (`loops/:id/trigger/`, PSAK auth). PSAK scopes are project-wide by design,
    so this bypasses the personal/team visibility split entirely (see LOOPS.md "API trigger auth")."""
    loop = Loop.objects.filter(team_id=team_id, deleted=False, pk=loop_id).first()
    if loop is None:
        return None

    trigger = (
        LoopTrigger.objects.filter(loop=loop, type=LoopTrigger.TriggerType.API, enabled=True)
        .order_by("created_at")
        .first()
    )
    if trigger is None:
        return LoopFireResult(created=False, reason="disabled", task_id=None, task_run_id=None)

    fire_key = idempotency_key or f"api-{uuid4().hex}"
    trigger_context = loop_runs.render_trigger_context("api", payload, loop)
    return loop_runs.fire_loop(
        loop=loop, trigger=trigger, fire_key=fire_key, trigger_context=trigger_context, actor=None
    )


# --- Preview ---


def preview_loop(
    loop_id: str | UUID, team_id: int, user: User | None, sample_payload: dict | None = None
) -> LoopPreviewDTO | None:
    """Dry run: renders instructions + trigger context without creating a task, run, or side
    effects. `sample_payload` is `{"trigger_type": ..., "payload": ...}`; omitted entirely (or
    `trigger_type` omitted) defaults to a synthetic schedule fire."""
    user_id = getattr(user, "id", None)
    loop = _visible_loop_queryset(team_id, user_id).filter(pk=loop_id).first()
    if loop is None:
        return None

    sample_payload = sample_payload or {}
    trigger_type = sample_payload.get("trigger_type") or LoopTrigger.TriggerType.SCHEDULE
    payload = sample_payload.get("payload")
    trigger_context = loop_runs.render_trigger_context(trigger_type, payload, loop)
    return LoopPreviewDTO(instructions=loop.instructions, trigger_type=trigger_type, trigger_context=trigger_context)


# --- Run history ---


def _encode_run_cursor(run: TaskRun) -> str:
    payload = {"created_at": run.created_at.isoformat(), "id": str(run.id)}
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")


def _decode_run_cursor(cursor: str) -> tuple[datetime, UUID] | None:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8"))
        return datetime.fromisoformat(payload["created_at"]), UUID(payload["id"])
    except (ValueError, KeyError, TypeError):
        return None


def list_loop_runs(
    loop_id: str | UUID,
    team_id: int,
    user: User | None,
    *,
    cursor: str | None = None,
    limit: int = DEFAULT_LOOP_RUN_PAGE_SIZE,
) -> LoopRunPageDTO | None:
    """TaskRun rows spawned by this loop's firings, newest first, cursor-paginated.

    Matched primarily via the indexed `Task.loop` FK, set on every task `fire_loop` creates.
    Also matches on the legacy `TaskRun.state["loop_id"]` snapshot key so runs created before
    the FK existed still show up; that side of the OR is an unindexed JSON lookup, but it is
    scoped to `team_id` first and only ever touches historical rows going forward.
    """
    user_id = getattr(user, "id", None)
    loop = _visible_loop_queryset(team_id, user_id).filter(pk=loop_id).first()
    if loop is None:
        return None

    page_size = max(1, min(limit, MAX_LOOP_RUN_PAGE_SIZE))
    queryset = (
        TaskRun.objects.filter(team_id=team_id)
        .filter(Q(task__loop_id=loop.id) | Q(state__loop_id=str(loop.id)))
        .order_by("-created_at", "-id")
    )

    if cursor:
        decoded = _decode_run_cursor(cursor)
        if decoded is not None:
            cursor_created_at, cursor_id = decoded
            queryset = queryset.filter(
                Q(created_at__lt=cursor_created_at) | (Q(created_at=cursor_created_at) & Q(id__lt=cursor_id))
            )

    rows = list(queryset[: page_size + 1])
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    next_cursor = _encode_run_cursor(rows[-1]) if has_more and rows else None
    return LoopRunPageDTO(runs=[_task_run_to_loop_run_dto(run) for run in rows], next_cursor=next_cursor)


__all__ = [
    "ALLOWED_GITHUB_TRIGGER_EVENTS",
    "IDENTITY_FIELDS",
    "MAX_FIX_ITERATIONS_CEILING",
    "MAX_LOOP_REPOSITORIES",
    "NOTIFICATION_CHANNELS",
    "NOTIFICATION_EVENTS",
    "POSTHOG_MCP_SCOPES_CHOICES",
    "LoopBehaviorsDTO",
    "LoopConnectorsDTO",
    "LoopContextOutputsDTO",
    "LoopContextTargetDTO",
    "LoopDTO",
    "LoopFireResult",
    "LoopNotificationChannelDTO",
    "LoopNotificationsDTO",
    "LoopOverlapPolicy",
    "LoopLimitError",
    "LoopPermissionError",
    "MAX_LOOPS_PER_TEAM",
    "MAX_TRIGGERS_PER_LOOP",
    "LoopPreviewDTO",
    "LoopRepositoryEntryDTO",
    "LoopRunDTO",
    "LoopRunPageDTO",
    "LoopScheduleSyncStatus",
    "LoopTriggerDTO",
    "LoopTriggerType",
    "LoopVisibility",
    "active_mcp_installation_ids",
    "create_loop",
    "desktop_canvas_exists",
    "desktop_folder_exists",
    "fire_loop_api",
    "fire_loop_manual",
    "get_loop",
    "github_integration_ids_for_team",
    "list_loop_runs",
    "list_loops",
    "pause_loops_for_deactivated_user",
    "pause_loops_referencing_integrations",
    "preview_loop",
    "sandbox_environment_queryset",
    "soft_delete_loop",
    "update_loop",
    "visible_loop_ids",
]
