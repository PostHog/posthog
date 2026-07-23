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
import logging
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from django.db import connection, transaction
from django.db.models import Q, QuerySet

from pydantic import Field
from pydantic.dataclasses import dataclass

from posthog.models import User
from posthog.models.file_system.file_system import FileSystem
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.rbac.user_access_control import AccessControlLevel, UserAccessControl

from products.mcp_store.backend.facade.api import get_active_installations
from products.tasks.backend import loop_service
from products.tasks.backend.logic.services import loop_runs
from products.tasks.backend.loop_lifecycle import (
    pause_loops_for_deactivated_user,
    pause_loops_for_removed_member,
    pause_loops_referencing_integrations,
)
from products.tasks.backend.models import Loop, LoopTrigger, SandboxEnvironment, Task, TaskRun

logger = logging.getLogger(__name__)

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
# scheduler. Raising them is a deliberate, per-request-to-support decision. This is the single
# source of truth for the cap: the list endpoint returns it so the frontend gates creation
# against this number rather than hardcoding its own, keeping the two from drifting.
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
        "skill_bundles",
    }
)
_PAUSE_FIELD = "enabled"

# Nested JSON config fields written through DRF nested serializers. A PATCH sends these as partial
# dicts, so `update_loop` deep-merges them onto the stored value rather than replacing wholesale.
_NESTED_MERGE_FIELDS: frozenset[str] = frozenset({"behaviors", "connectors", "notifications", "context_target"})


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge `overlay` onto `base`: overlay wins, nested dicts merge, lists and scalars
    replace. Lets a partial PATCH of a nested loop config preserve the subfields it omits."""
    merged = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        merged[key] = _deep_merge(existing, value) if isinstance(value, dict) and isinstance(existing, dict) else value
    return merged


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


class LoopValidationError(Exception):
    """Raised when a facade-level write fails a cross-team or shape check. The DRF serializer
    catches these cases first for API callers; this is the backstop for in-code facade callers
    (internal products) that don't re-run serializer validation, so they can't create a loop that
    references another team's resources or explodes at fire time. Cross-field checks that need
    the loop's current state (context attachment vs visibility) live only here, so the view
    layer translates this to a 400."""


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
class LoopSkillBundleDTO:
    """A skill bundle attached to a loop, sans storage internals. `content_sha256` lets the
    client detect when its local copy of the skill has drifted from the stored snapshot."""

    id: str
    skill_name: str
    skill_source: str
    size: int
    content_sha256: str
    uploaded_at: str


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
    disabled_reason: str | None
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
    skill_bundles: list[LoopSkillBundleDTO] = Field(default_factory=list)


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


# These DTO builders read JSON columns that the DRF serializer validates at the API edge, but a
# facade-bypass write, a backfill, or a schema evolution could still leave a malformed shape on a
# row. They must never raise: one bad row would otherwise break every list read of the team's
# loops. So each guards its input to a dict and coerces defensively.


def _as_dict(raw: object) -> dict:
    return raw if isinstance(raw, dict) else {}


def _coerce_int(value: object, default: int) -> int:
    if not isinstance(value, (int, float, str)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _behaviors_dto(raw: dict | None) -> LoopBehaviorsDTO:
    raw = _as_dict(raw)
    return LoopBehaviorsDTO(
        create_prs=bool(raw.get("create_prs", False)),
        watch_ci=bool(raw.get("watch_ci", False)),
        fix_review_comments=bool(raw.get("fix_review_comments", False)),
        max_fix_iterations=_coerce_int(
            raw.get("max_fix_iterations", DEFAULT_MAX_FIX_ITERATIONS), DEFAULT_MAX_FIX_ITERATIONS
        ),
    )


def _notification_channel_dto(raw: dict | None) -> LoopNotificationChannelDTO:
    raw = _as_dict(raw)
    events = raw.get("events")
    return LoopNotificationChannelDTO(
        enabled=bool(raw.get("enabled", False)),
        events=[event for event in events if isinstance(event, str)] if isinstance(events, list) else [],
        params=_as_dict(raw.get("params")),
    )


def _notifications_dto(raw: dict | None) -> LoopNotificationsDTO:
    raw = _as_dict(raw)
    return LoopNotificationsDTO(
        push=_notification_channel_dto(raw.get("push")),
        email=_notification_channel_dto(raw.get("email")),
        slack=_notification_channel_dto(raw.get("slack")),
    )


def _connectors_dto(raw: dict | None) -> LoopConnectorsDTO:
    raw = _as_dict(raw)
    mcp_installation_ids = raw.get("mcp_installation_ids")
    return LoopConnectorsDTO(
        mcp_installation_ids=[str(x) for x in mcp_installation_ids] if isinstance(mcp_installation_ids, list) else [],
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
        disabled_reason=loop.disabled_reason,
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
        skill_bundles=_skill_bundle_dtos(loop.skill_bundles),
    )


def _skill_bundle_dtos(entries: list | None) -> list[LoopSkillBundleDTO]:
    dtos: list[LoopSkillBundleDTO] = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        metadata = entry.get("metadata") or {}
        dtos.append(
            LoopSkillBundleDTO(
                id=str(entry.get("id", "")),
                skill_name=str(metadata.get("skill_name", "")),
                skill_source=str(metadata.get("skill_source", "")),
                size=int(entry.get("size", 0)),
                content_sha256=str(metadata.get("content_sha256", "")),
                uploaded_at=str(entry.get("uploaded_at", "")),
            )
        )
    return dtos


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


def _rbac_denied(loop: Loop, user: User | None, required_level: AccessControlLevel) -> bool:
    """Object-level RBAC for `AccessControl` rows with resource="loop". The viewset never calls
    `get_object()`/`check_object_permissions` (the facade owns object loading), so without this an
    admin-configured per-loop grant is enforced only at resource level: `AccessControlPermission.
    has_permission` admits anyone with a grant on ANY loop, expecting an object check that would
    otherwise never run. `user=None` means a PSAK/service caller, which object-level RBAC does not
    apply to (matching `AccessControlPermission.has_object_permission`). Loop owners always pass
    via the RBAC creator precheck."""
    if user is None:
        return False
    uac = UserAccessControl(user=user, team=loop.team)
    return not uac.check_access_level_for_object(loop, required_level=required_level)


def _rbac_filter_visible(loops: QuerySet[Loop], team_id: int, user: User | None) -> QuerySet[Loop]:
    if user is None:
        return loops
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return loops.none()
    return UserAccessControl(user=user, team=team).filter_queryset_by_access_level(loops)


def _is_owner(loop: Loop, user: User | None) -> bool:
    return user is not None and loop.created_by_id == user.id


def _is_creator(loop: Loop, user: User | None) -> bool:
    # `creator` is immutable (unlike `created_by`, which takeover reassigns), so it is the authority
    # for destructive/visibility operations that a takeover must not confer on whoever grabbed the loop.
    return user is not None and loop.creator_id == user.id


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
    # RBAC before the visibility rules: a loop the user may not even view stays a 404, while one
    # they can view but not edit is a clean 403.
    if _rbac_denied(loop, user, "viewer"):
        return None
    if _rbac_denied(loop, user, "editor"):
        raise LoopPermissionError("You do not have editor access to this loop.")
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
    identity_edits = {field_name for field_name in validated_data if field_name in IDENTITY_FIELDS}
    if identity_edits:
        # A project admin may change a team loop's visibility (the un-share / kill-switch authority,
        # further gated to team->personal in `update_loop`), but every other identity edit still
        # requires ownership.
        if identity_edits <= {"visibility"} and _is_team_admin(loop, user):
            return
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


def team_github_integration_ids(team_id: int) -> set[int]:
    """Every GitHub integration id for a team. Lets loop-repository validation tell
    'this project has none' apart from 'you passed the wrong id'."""
    return set(Integration.objects.filter(team_id=team_id, kind="github").values_list("id", flat=True))


def repository_accessible_via_integration(team_id: int, integration_id: int, full_name: str) -> bool:
    """Whether `full_name` (`owner/name`) is a repository the given GitHub integration can actually
    reach. A GitHub App installation can be shared across projects, so verifying only that the
    integration row belongs to the team is not enough: a member could otherwise point a loop at
    another project's private repo and have it read or written through the installation-wide token.

    Fails closed. `list_all_cached_repositories` refreshes a cold or stale cache from GitHub, and we
    accept only an exact match against the resulting list. A missing/invalidated cache is a normal
    state, so treating it as permissive would leave the cross-project boundary bypassable; if the
    list can't be resolved (refresh error, no snapshot) we reject rather than authorize."""
    integration = Integration.objects.filter(team_id=team_id, kind="github", id=integration_id).first()
    if integration is None:
        return False
    normalized = full_name.strip().lower()
    try:
        repositories = GitHubIntegration(integration).list_all_cached_repositories()
    except Exception:
        logger.warning(
            "loop_repository_access_check_unavailable",
            exc_info=True,
            extra={"team_id": team_id, "integration_id": integration_id},
        )
        return False
    return any(isinstance(repo, dict) and str(repo.get("full_name", "")).lower() == normalized for repo in repositories)


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


def count_team_loops(team_id: int) -> int:
    """Authoritative count of a project's user-facing loops, measured against `MAX_LOOPS_PER_TEAM`.
    Excludes deleted loops and `internal=True` loops (backend-created loops don't consume the
    user-facing quota). This is the number the create path checks and the list endpoint reports,
    so the frontend can show remaining capacity without duplicating the counting rule."""
    return Loop.objects.for_team(team_id, canonical=True).filter(deleted=False, internal=False).count()


def list_loops(team_id: int, user: User | None) -> list[LoopDTO]:
    user_id = getattr(user, "id", None)
    loops = (
        _visible_loop_queryset(team_id, user_id)
        .select_related("sandbox_environment")
        .prefetch_related("triggers")
        .order_by("-created_at")
    )
    loops = _rbac_filter_visible(loops, team_id, user)
    return [_loop_to_dto(loop) for loop in loops]


def visible_loop_ids(team_id: int, user: User | None) -> set[str]:
    """Ids of loops the user may see, as strings. For callers outside request/team scope
    (e.g. the activity-log viewset restricting `Loop`-scoped rows): uses `for_team` explicitly
    so it never depends on ambient team context, unlike `list_loops`/`_visible_loop_queryset`.
    Applies the same object-level RBAC filter as `list_loops`, so a loop hidden from the list
    can't leak its config history through the activity feed instead."""
    user_id = getattr(user, "id", None)
    visibility_q = Q(visibility=Loop.Visibility.TEAM)
    if user_id is not None:
        visibility_q |= Q(created_by_id=user_id)
    loops = Loop.objects.for_team(team_id, canonical=True).filter(deleted=False, internal=False).filter(visibility_q)
    visible = _rbac_filter_visible(loops, team_id, user)
    return {str(loop_id) for loop_id in visible.values_list("id", flat=True)}


def hidden_personal_loop_ids_for_org(organization_id: str | UUID, user: User | None) -> set[str]:
    """Ids of personal loops across an org NOT owned by `user`, as strings. The org-wide activity-log
    feed (org admins/owners) must still keep other people's personal-loop config out, since personal
    loops are owner-only (see LOOPS.md "Access control"). Cross-team by design, hence `unscoped()`."""
    user_id = getattr(user, "id", None)
    hidden = Loop.objects.unscoped().filter(team__organization_id=organization_id, visibility=Loop.Visibility.PERSONAL)
    if user_id is not None:
        hidden = hidden.exclude(created_by_id=user_id)
    return {str(loop_id) for loop_id in hidden.values_list("id", flat=True)}


def get_loop(loop_id: str | UUID, team_id: int, user: User | None) -> LoopDTO | None:
    user_id = getattr(user, "id", None)
    loop = (
        _visible_loop_queryset(team_id, user_id)
        .select_related("team")
        .prefetch_related("triggers")
        .filter(pk=loop_id)
        .first()
    )
    if loop is None or _rbac_denied(loop, user, "viewer"):
        return None
    return _loop_to_dto(loop)


# --- Internal loops ---
# `internal=True` loops are created by a backend flow (e.g. signals scheduling a one-off PR
# follow-up) and are never reachable through the user-facing CRUD above, which filters
# `internal=False`. These give the owning product a way to read and tear them down. No user or
# visibility checks: there is no owning end user, and the caller is trusted server code.


def get_internal_loop(loop_id: str | UUID, team_id: int) -> LoopDTO | None:
    # team_scope: internal callers run outside request scope, and _loop_to_dto reads the
    # `triggers` related manager (fail-closed), which needs ambient team context.
    with team_scope(team_id, canonical=True):
        loop = Loop.objects.filter(deleted=False, internal=True, pk=loop_id).prefetch_related("triggers").first()
        return _loop_to_dto(loop) if loop is not None else None


def list_internal_loops(team_id: int, *, origin_product: str | None = None) -> list[LoopDTO]:
    with team_scope(team_id, canonical=True):
        loops = Loop.objects.filter(deleted=False, internal=True).prefetch_related("triggers").order_by("-created_at")
        if origin_product is not None:
            loops = loops.filter(origin_product=origin_product)
        return [_loop_to_dto(loop) for loop in loops]


def delete_team_loop_schedules(team_id: int) -> None:
    """Tear down every loop trigger's Temporal Schedule for a team. Called from the core
    team-deletion workflow before the LoopTrigger rows are cascaded away, since Django's CASCADE
    never talks to Temporal and the Schedule would otherwise fire forever into a deleted trigger."""
    loop_service.delete_schedules_for_team(team_id)


def delete_internal_loop(loop_id: str | UUID, team_id: int) -> bool:
    """Soft-delete an internal loop and delete its Temporal Schedules. Returns False if not found."""
    loop = Loop.objects.for_team(team_id, canonical=True).filter(deleted=False, internal=True, pk=loop_id).first()
    if loop is None:
        return False
    loop.deleted = True
    loop.save(update_fields=["deleted", "updated_at"])
    loop_service.delete_loop_schedules(loop)
    return True


def validate_loop_write(team_id: int, data: dict) -> None:
    """Enforce the cross-team and cardinality checks the write serializer performs, so an in-code
    facade caller can't reference another team's GitHub integration or SandboxEnvironment or
    exceed the repository cap. Raises `LoopValidationError`. Model/reasoning validity is left to
    fire time (a clear, self-contained failure) to keep the model catalog off this import path."""
    repositories = data.get("repositories")
    if repositories is not None:
        if len(repositories) > MAX_LOOP_REPOSITORIES:
            raise LoopValidationError(f"A loop can operate on at most {MAX_LOOP_REPOSITORIES} repositories.")
        integration_ids = {
            int(entry["github_integration_id"])
            for entry in repositories
            if isinstance(entry, dict) and entry.get("github_integration_id") is not None
        }
        if integration_ids:
            owned = github_integration_ids_for_team(team_id, integration_ids)
            missing = integration_ids - owned
            if missing:
                raise LoopValidationError(f"GitHub integration(s) not found for this team: {sorted(missing)}.")
        # Bind each repository to its integration's accessible list, not just the team: a shared
        # installation must not let a loop reach a repo the selected integration can't.
        for entry in repositories:
            if not isinstance(entry, dict):
                continue
            entry_integration_id = entry.get("github_integration_id")
            full_name = entry.get("full_name")
            if entry_integration_id is None or not full_name:
                continue
            if not repository_accessible_via_integration(team_id, int(entry_integration_id), str(full_name)):
                raise LoopValidationError(
                    f"Repository '{full_name}' is not accessible via the selected GitHub integration."
                )

    sandbox_environment_id = data.get("sandbox_environment_id")
    if sandbox_environment_id is not None:
        if not SandboxEnvironment.objects.filter(team_id=team_id, id=sandbox_environment_id).exists():
            raise LoopValidationError("Sandbox environment not found for this team.")


def _validate_context_visibility(visibility: str, context_target: dict | None) -> None:
    """A context-attached loop must be team-visible: its runs land in the context's public feed
    channel and maintain team-shared artifacts, so `personal` would leak the loop's output to
    the whole team while hiding the loop that produces it."""
    if context_target and visibility != Loop.Visibility.TEAM:
        raise LoopValidationError("A loop attached to a context must have team visibility.")


def create_loop(team_id: int, user: User | None, validated_data: dict) -> LoopDTO:
    data = dict(validated_data)
    validate_loop_write(team_id, data)
    _validate_context_visibility(data.get("visibility", Loop.Visibility.PERSONAL), data.get("context_target"))
    trigger_payloads = data.pop("triggers", None) or []

    if len(trigger_payloads) > MAX_TRIGGERS_PER_LOOP:
        raise LoopLimitError(
            code="max_triggers_per_loop",
            limit=MAX_TRIGGERS_PER_LOOP,
            detail=f"A loop can have at most {MAX_TRIGGERS_PER_LOOP} triggers.",
        )

    with transaction.atomic():
        # Serialize a team's loop creation on the same advisory lock fire_loop uses, so concurrent
        # creates can't each read a below-cap count and collectively overshoot MAX_LOOPS_PER_TEAM.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"loop-team:{team_id}"])
        # internal=False: backend-created internal loops must not consume the user-facing quota.
        if count_team_loops(team_id) >= MAX_LOOPS_PER_TEAM:
            raise LoopLimitError(
                code="max_loops_per_team",
                limit=MAX_LOOPS_PER_TEAM,
                detail=(
                    f"This project has reached the limit of {MAX_LOOPS_PER_TEAM} loops. "
                    "Delete a loop to make room, or contact support to raise the limit."
                ),
            )
        loop = Loop.objects.create(
            team_id=team_id,
            created_by_id=getattr(user, "id", None),
            creator_id=getattr(user, "id", None),
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

    data = dict(validated_data)
    # Explicit ownership takeover on a team loop: a member who wants to edit identity-bearing
    # config claims ownership in the same request. Only a team loop can be taken over, and only
    # by a member who can already reach it (fetched above). This is the documented mechanism for
    # editing a teammate's team loop, replacing the never-implemented "implicit takeover".
    take_ownership = bool(data.pop("take_ownership", False))
    if take_ownership and user is not None and loop.visibility == Loop.Visibility.TEAM and not _is_owner(loop, user):
        # Taking ownership unlocks editing a teammate's identity config, but must NOT double as a way
        # to privatize a shared team loop in the same request. Changing visibility stays owner-only,
        # judged against the pre-takeover owner, so a non-owner can't grab the loop and hide it from
        # the team in one PATCH. Other identity edits are the whole point of takeover, so they pass.
        if "visibility" in data:
            raise LoopPermissionError("Taking ownership cannot change a loop's visibility in the same request.")
        loop.created_by_id = user.id

    _authorize_update(loop, user, data)
    # Un-sharing a team loop (team -> personal) removes it from the team while letting the actor keep
    # its config privately. Restrict that to a project admin, so a member who took a shared loop over
    # can't then privatize it out from under the team. The same-request takeover guard above only
    # covers the one-PATCH version; this also catches doing it in a second request as the new owner.
    if (
        data.get("visibility") == Loop.Visibility.PERSONAL
        and loop.visibility == Loop.Visibility.TEAM
        and not (_is_creator(loop, user) or _is_team_admin(loop, user))
    ):
        raise LoopPermissionError("Only the loop's creator or a project admin may make a shared team loop personal.")
    validate_loop_write(team_id, data)

    trigger_payloads = data.pop("triggers", None)
    # Detaching from a context sends `context_target: null`; the column is NOT NULL, so store {}.
    detaching_context = "context_target" in data and data["context_target"] is None
    if detaching_context:
        data["context_target"] = {}

    # Judged on the effective post-update state: attaching a context to a personal loop and
    # downgrading an attached loop to personal must both be rejected.
    _validate_context_visibility(
        data.get("visibility", loop.visibility),
        data["context_target"] if "context_target" in data else loop.context_target,
    )

    enabled_before = loop.enabled
    with transaction.atomic():
        for field_name, value in data.items():
            # Nested JSON configs arrive as partial dicts on a PATCH (DRF drops omitted nested
            # subfields under a partial parent), so a blind setattr would wipe the siblings the
            # client didn't resend. Merge onto the stored value instead. A context detach is a full
            # replace (clear to {}), not a merge.
            if (
                field_name in _NESTED_MERGE_FIELDS
                and isinstance(value, dict)
                and not (field_name == "context_target" and detaching_context)
            ):
                current = getattr(loop, field_name)
                if isinstance(current, dict):
                    value = _deep_merge(current, value)
            setattr(loop, field_name, value)
        # Re-enabling clears the lifecycle pause reason (owner reactivated, integration
        # reconnected), so the UI stops showing a stale "paused because ..." explanation.
        if "enabled" in data and loop.enabled and not enabled_before:
            loop.disabled_reason = None
        loop.save()

    # Toggling `enabled` must drive the Temporal Schedules, not just the row. Without this,
    # re-enabling a loop after an auto-pause (the documented recovery) returns 200 but never
    # resumes its schedule, so the loop silently never fires again. When triggers are being
    # re-synced in the same call, `_sync_triggers` already re-evaluates schedule state, so skip
    # the redundant pause/resume here.
    if trigger_payloads is None and "enabled" in data and loop.enabled != enabled_before:
        if loop.enabled:
            loop_service.resume_loop_schedules(loop)
        else:
            loop_service.pause_loop_schedules(loop)

    if trigger_payloads is not None:
        _sync_triggers(loop, trigger_payloads)

    loop.refresh_from_db()
    return _loop_to_dto(loop)


MAX_LOOP_SKILL_BUNDLES = 10
# Decoded per-bundle ceiling. The request is JSON with base64 content and Django's
# DATA_UPLOAD_MAX_MEMORY_SIZE (20MB) bounds the raw body first, leaving roughly 15MB of
# decoded budget per request — 10MB keeps this advertised limit honestly reachable
# within it instead of promising the run-artifact 30MB that a JSON upload can never hit.
MAX_LOOP_SKILL_BUNDLE_SIZE_BYTES = 10 * 1024 * 1024


def _delete_skill_bundle_objects(loop_id: UUID, paths: list[str]) -> None:
    """Best-effort removal of loop skill bundle objects. Failures are logged, not raised:
    a leaked object is recoverable garbage, while failing the caller's operation over
    cleanup is not."""
    if not paths:
        return
    from posthog.storage import object_storage  # noqa: PLC0415 — keep storage deps off the api import path

    try:
        object_storage.delete_objects(paths)
    except Exception as exc:
        logger.warning(
            "loop.skill_bundle_cleanup_failed",
            extra={"loop_id": str(loop_id), "paths": paths, "error": str(exc)},
        )


def replace_loop_skill_bundles(
    loop_id: str | UUID, team_id: int, user: User | None, *, bundles: list[dict]
) -> LoopDTO | None:
    """Replace the loop's attached skill bundles wholesale — the client sends the full
    declarative set on every save, so there is no per-bundle add/remove surface. Bundle
    bytes land under the loop's own S3 prefix (not any run's, so run retention never
    reaps them). Every bundle is validated before the first byte is written, a failed
    write deletes what this request already wrote, and the manifest swap happens under
    a row lock with superseded paths read from the locked row — so neither a partial
    failure nor a concurrent replace strands unreferenced objects. Owner-gated like
    every other identity-bearing field. Returns `None` if the loop is not
    found/reachable."""
    import hashlib  # noqa: PLC0415

    from django.utils import timezone as django_timezone  # noqa: PLC0415

    from posthog.storage import object_storage  # noqa: PLC0415 — keep storage deps off the api import path

    from products.tasks.backend.logic.services.staged_artifacts import get_safe_artifact_name  # noqa: PLC0415

    if len(bundles) > MAX_LOOP_SKILL_BUNDLES:
        raise LoopValidationError(f"A loop can carry at most {MAX_LOOP_SKILL_BUNDLES} skill bundles.")

    loop = _fetch_loop_for_write(loop_id, team_id, user)
    if loop is None:
        return None
    _authorize_update(loop, user, {"skill_bundles": bundles})

    decoded: list[tuple[dict, bytes]] = []
    for bundle in bundles:
        try:
            content_bytes = base64.b64decode(bundle["content_base64"], validate=True)
        except (ValueError, TypeError):
            raise LoopValidationError(f"Skill bundle for '{bundle['skill_name']}' is not valid base64.")
        if len(content_bytes) > MAX_LOOP_SKILL_BUNDLE_SIZE_BYTES:
            raise LoopValidationError(
                f"Skill bundle for '{bundle['skill_name']}' exceeds the "
                f"{MAX_LOOP_SKILL_BUNDLE_SIZE_BYTES // (1024 * 1024)}MB limit."
            )
        if hashlib.sha256(content_bytes).hexdigest() != bundle["content_sha256"]:
            raise LoopValidationError(f"Skill bundle for '{bundle['skill_name']}' does not match its declared sha256.")
        decoded.append((bundle, content_bytes))

    prefix = loop.get_skill_bundle_s3_prefix()
    entries: list[dict] = []
    written_paths: list[str] = []
    try:
        for bundle, content_bytes in decoded:
            bundle_id = uuid4().hex
            safe_name = get_safe_artifact_name(bundle["file_name"])
            storage_path = f"{prefix}/{bundle_id[:8]}_{safe_name}"
            object_storage.write(storage_path, content_bytes, {"ContentType": "application/zip"})
            written_paths.append(storage_path)
            try:
                object_storage.tag(storage_path, {"team_id": str(loop.team_id)})
            except Exception as exc:
                logger.warning(
                    "loop.skill_bundle_tag_failed",
                    extra={"loop_id": str(loop.id), "storage_path": storage_path, "error": str(exc)},
                )
            entries.append(
                {
                    "id": bundle_id,
                    "name": safe_name,
                    "type": "skill_bundle",
                    "source": "posthog_code_skill",
                    "size": len(content_bytes),
                    "content_type": "application/zip",
                    "storage_path": storage_path,
                    "uploaded_at": django_timezone.now().isoformat(),
                    "metadata": {
                        "skill_name": bundle["skill_name"],
                        "skill_source": bundle["skill_source"],
                        "content_sha256": bundle["content_sha256"],
                        "bundle_format": "zip",
                        "schema_version": 1,
                    },
                }
            )
    except Exception:
        _delete_skill_bundle_objects(loop.id, written_paths)
        raise

    # Previous paths come from the row read under the lock, not the earlier fetch: if a
    # concurrent replace committed in between, its objects are what this swap supersedes
    # and must be the ones deleted, or they'd be stranded with no manifest referencing them.
    # A delete that committed in between is re-checked the same way — its lock-holder
    # already cleared the manifest, so this request must discard its own uploads instead
    # of resurrecting bundles on a deleted loop.
    previous_paths: list[str] = []
    lost_delete_race = False
    with transaction.atomic():
        locked = Loop.objects.unscoped().select_for_update().get(pk=loop.pk)
        if locked.deleted:
            lost_delete_race = True
        else:
            previous_paths = [
                entry["storage_path"]
                for entry in (locked.skill_bundles or [])
                if isinstance(entry, dict) and entry.get("storage_path")
            ]
            locked.skill_bundles = entries
            locked.save(update_fields=["skill_bundles", "updated_at"])

    if lost_delete_race:
        _delete_skill_bundle_objects(loop.id, written_paths)
        return None

    new_paths = {entry["storage_path"] for entry in entries}
    _delete_skill_bundle_objects(
        loop.id, [path for path in previous_paths if path.startswith(prefix) and path not in new_paths]
    )

    loop.refresh_from_db()
    return _loop_to_dto(loop)


def soft_delete_loop(loop_id: str | UUID, team_id: int, user: User | None) -> bool:
    loop = _fetch_loop_for_write(loop_id, team_id, user)
    if loop is None:
        return False

    # Deleting a team loop removes a shared automation the whole team may rely on, so it takes admin
    # authority (the documented kill switch) rather than mere ownership — otherwise a member who took
    # the loop over could delete it. A personal loop stays deletable by its owner.
    if loop.visibility == Loop.Visibility.TEAM:
        if not (_is_creator(loop, user) or _is_team_admin(loop, user)):
            raise LoopPermissionError("Only the loop's creator or a project admin may delete a shared team loop.")
    elif not (_is_owner(loop, user) or _is_team_admin(loop, user)):
        raise LoopPermissionError("Only the owner or a project admin may delete a loop.")

    # A deleted loop never fires again, so its skill bundle objects are dead weight with
    # no retention TTL — release them now and clear the manifest so the row stays honest.
    # The paths are read under the same row lock the skill-bundle replace takes, so a
    # replace racing this delete either commits first (its objects are what we read and
    # remove here) or locks after us, sees `deleted`, and cleans up its own uploads.
    with transaction.atomic():
        locked = Loop.objects.unscoped().select_for_update().get(pk=loop.pk)
        bundle_paths = [
            entry["storage_path"]
            for entry in (locked.skill_bundles or [])
            if isinstance(entry, dict) and entry.get("storage_path")
        ]
        locked.deleted = True
        locked.skill_bundles = []
        locked.save(update_fields=["deleted", "skill_bundles", "updated_at"])
    loop.deleted = True
    _delete_skill_bundle_objects(loop.id, bundle_paths)
    loop_service.delete_loop_schedules(loop)
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
    # Triggers repointed away from `schedule`: their old Temporal Schedule must be torn down, but
    # only after the DB commits. Deleting it inside the atomic block means a rollback reverts the
    # row to SCHEDULE while the Schedule is already irreversibly gone. `delete_loop_trigger_schedule`
    # keys off the stable `schedule_id`, not the row's type, so a post-commit delete still reaches it.
    schedules_to_delete: list[LoopTrigger] = []

    with transaction.atomic():
        for payload in trigger_payloads:
            trigger_id = payload.get("id")
            existing = existing_by_id.get(trigger_id) if trigger_id else None
            if existing is not None:
                if existing.type == LoopTrigger.TriggerType.SCHEDULE and payload["type"] != existing.type:
                    schedules_to_delete.append(existing)
                existing.type = payload["type"]
                # Preserve the current value when a resent trigger omits `enabled` (a PATCH drops
                # omitted nested fields), so re-sending a trigger never silently re-enables it.
                existing.enabled = payload.get("enabled", existing.enabled)
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

    for trigger in schedules_to_delete:
        loop_service.delete_loop_trigger_schedule(trigger)

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
    loop = _visible_loop_queryset(team_id, user_id).select_related("team").filter(pk=loop_id).first()
    if loop is None or _rbac_denied(loop, user, "viewer"):
        return None
    if _rbac_denied(loop, user, "editor"):
        raise LoopPermissionError("You do not have editor access to this loop.")

    fire_key = idempotency_key or f"manual-{uuid4().hex}"
    trigger_context = loop_runs.render_trigger_context("manual", None, loop)
    return loop_runs.fire_loop(loop=loop, trigger=None, fire_key=fire_key, trigger_context=trigger_context, actor=user)


def _fire_api_trigger(
    loop: Loop, payload: dict | None, idempotency_key: str | None, actor: User | None
) -> LoopFireResult:
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
        loop=loop, trigger=trigger, fire_key=fire_key, trigger_context=trigger_context, actor=actor
    )


def fire_loop_api(
    loop_id: str | UUID, team_id: int, payload: dict | None, idempotency_key: str | None = None
) -> LoopFireResult | None:
    """External fire (`loops/:id/trigger/`, PSAK auth). A PSAK is a project-scoped service
    credential, so this is project-wide by design and bypasses the personal/team visibility split
    (see LOOPS.md "API trigger auth"). Non-PSAK (session/PAT/OAuth) callers of the same endpoint
    go through `fire_loop_api_for_user` instead, which re-imposes that split."""
    # `internal=False`: internal loops are driven by their backend flow, never externally
    # firable, even though a PSAK is project-wide (mirrors the read/write API surface).
    loop = Loop.objects.filter(team_id=team_id, deleted=False, internal=False, pk=loop_id).first()
    if loop is None:
        return None
    return _fire_api_trigger(loop, payload, idempotency_key, actor=None)


def fire_loop_api_for_user(
    loop_id: str | UUID, team_id: int, user: User | None, payload: dict | None, idempotency_key: str | None = None
) -> LoopFireResult | None:
    """API-trigger fire for a non-PSAK caller (a real session/PAT/OAuth user, not a project-wide
    service credential). Owner-only: the request payload becomes agent prompt content and the run
    executes as the loop's owner (`loop.created_by`), so letting a non-owner teammate trigger a
    team loop with an arbitrary payload would run injected instructions under the owner's
    OAuth/GitHub/MCP authority. Project-wide service triggering goes through PSAK + `fire_loop_api`;
    a member who wants to fire a team loop as themselves uses the manual `run` action. `None` means
    not found or not owned by the caller."""
    user_id = getattr(user, "id", None)
    if user_id is None:
        return None
    loop = Loop.objects.filter(
        team_id=team_id, deleted=False, internal=False, pk=loop_id, created_by_id=user_id
    ).first()
    if loop is None:
        return None
    return _fire_api_trigger(loop, payload, idempotency_key, actor=user)


# --- Preview ---


def preview_loop(
    loop_id: str | UUID, team_id: int, user: User | None, sample_payload: dict | None = None
) -> LoopPreviewDTO | None:
    """Dry run: renders instructions + trigger context without creating a task, run, or side
    effects. `sample_payload` is `{"trigger_type": ..., "payload": ...}`; omitted entirely (or
    `trigger_type` omitted) defaults to a synthetic schedule fire."""
    user_id = getattr(user, "id", None)
    loop = _visible_loop_queryset(team_id, user_id).select_related("team").filter(pk=loop_id).first()
    if loop is None or _rbac_denied(loop, user, "viewer"):
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
    loop = _visible_loop_queryset(team_id, user_id).select_related("team").filter(pk=loop_id).first()
    if loop is None or _rbac_denied(loop, user, "viewer"):
        return None
    return _loop_runs_page(loop, team_id, cursor=cursor, limit=limit)


def list_loop_runs_for_service(
    loop_id: str | UUID,
    team_id: int,
    *,
    cursor: str | None = None,
    limit: int = DEFAULT_LOOP_RUN_PAGE_SIZE,
) -> LoopRunPageDTO | None:
    """Run history for a PSAK-authenticated service caller: project-wide, no personal/team
    visibility filter (a PSAK can already trigger any loop in the project — see `fire_loop_api`)."""
    loop = Loop.objects.filter(team_id=team_id, deleted=False, internal=False, pk=loop_id).first()
    if loop is None:
        return None
    return _loop_runs_page(loop, team_id, cursor=cursor, limit=limit)


def _loop_runs_page(loop: Loop, team_id: int, *, cursor: str | None, limit: int) -> LoopRunPageDTO:
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
    "LoopValidationError",
    "validate_loop_write",
    "MAX_LOOPS_PER_TEAM",
    "MAX_TRIGGERS_PER_LOOP",
    "LoopPreviewDTO",
    "LoopRepositoryEntryDTO",
    "LoopRunDTO",
    "LoopRunPageDTO",
    "LoopScheduleSyncStatus",
    "LoopSkillBundleDTO",
    "MAX_LOOP_SKILL_BUNDLES",
    "MAX_LOOP_SKILL_BUNDLE_SIZE_BYTES",
    "LoopTriggerDTO",
    "LoopTriggerType",
    "LoopVisibility",
    "active_mcp_installation_ids",
    "count_team_loops",
    "create_loop",
    "delete_internal_loop",
    "delete_team_loop_schedules",
    "desktop_canvas_exists",
    "desktop_folder_exists",
    "fire_loop_api",
    "fire_loop_api_for_user",
    "fire_loop_manual",
    "get_internal_loop",
    "get_loop",
    "list_internal_loops",
    "github_integration_ids_for_team",
    "list_loop_runs",
    "list_loop_runs_for_service",
    "list_loops",
    "pause_loops_for_deactivated_user",
    "pause_loops_for_removed_member",
    "pause_loops_referencing_integrations",
    "preview_loop",
    "replace_loop_skill_bundles",
    "repository_accessible_via_integration",
    "sandbox_environment_queryset",
    "soft_delete_loop",
    "update_loop",
    "visible_loop_ids",
    "hidden_personal_loop_ids_for_org",
]
