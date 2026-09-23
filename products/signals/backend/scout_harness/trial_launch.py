from __future__ import annotations

import json
import hashlib
from datetime import datetime
from typing import Literal, TypeVar, cast
from uuid import UUID

from django.conf import settings
from django.utils import timezone

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from posthog.models import Team, User
from posthog.storage import object_storage

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.agent_runtime import STEP_SCOUT, resolve_agent_runtime
from products.signals.backend.models import SignalScoutConfig, SignalScoutNote, SignalScoutRun, SignalScratchpad
from products.signals.backend.scout_harness.model_selection import resolve_scout_model
from products.signals.backend.scout_harness.serializers import validate_scout_repositories
from products.signals.backend.scout_harness.skill_loader import load_skill_for_run, skill_uses_report_channel
from products.signals.backend.scout_harness.tools.notes import _to_note
from products.signals.backend.scout_harness.tools.runs import search_recent_runs
from products.signals.backend.scout_harness.tools.scratchpad import _to_entry
from products.skills.backend.api.skill_services import get_skill_by_name_from_db
from products.tasks.backend.facade.run_config import (
    get_default_model_for_runtime_adapter,
    get_model_access_error,
    get_reasoning_effort_error,
    get_runtime_adapter_for_model,
)

MAX_TRIAL_CONTEXT_BYTES = 16 * 1024 * 1024
SCOUT_TRIAL_TASK_STATE_KEY = "scout_trial"


class ScoutTrialLaunchError(ValueError):
    pass


class TrialContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    id: UUID
    team_id: int
    config_id: UUID
    user_id: int
    created_at: datetime
    skill_name: str
    skill_version: int
    skill_body: str
    skill_origin: Literal["canonical", "custom"]
    allowed_tools: list[str]
    capabilities: dict[str, JsonValue]
    runtime_adapter: Literal["claude", "codex"]
    model: str
    reasoning_effort: str | None = None
    service_tier: str | None = None
    note: str = ""
    memory: list[dict[str, JsonValue]] = Field(default_factory=list)
    notes: list[dict[str, JsonValue]] = Field(default_factory=list)
    recent_runs: list[dict[str, JsonValue]] = Field(default_factory=list)


class TrialLaunch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    id: UUID
    team_id: int
    context_id: UUID
    config_id: UUID
    user_id: int
    created_at: datetime
    skill_name: str
    skill_version: int
    skill_body: str
    runtime_adapter: Literal["claude", "codex"]
    model: str
    reasoning_effort: str
    service_tier: str | None = None
    note: str = ""
    variant: str = ""
    request_hash: str


_Document = TypeVar("_Document", bound=BaseModel)


def _document_key(team_id: int, kind: Literal["contexts", "launches"], identifier: UUID) -> str:
    return f"signals/scout-trials/{team_id}/{kind}/{identifier}.json"


def _read_document(key: str, document_type: type[_Document]) -> _Document | None:
    content = object_storage.read(key, missing_ok=True)
    if content is None:
        return None
    return document_type.model_validate_json(content)


def _write_document_once(key: str, document: _Document) -> _Document:
    content = document.model_dump_json()
    if len(content.encode()) > MAX_TRIAL_CONTEXT_BYTES:
        raise ScoutTrialLaunchError("The saved scout context is too large for a live trial.")
    existing = _read_document(key, type(document))
    if existing is not None:
        return existing
    try:
        object_storage.write(key, content, extras={"ContentType": "application/json", "IfNoneMatch": "*"})
    except object_storage.ObjectStorageError:
        # A concurrent retry may have saved the same launch while this request prepared it.
        existing = _read_document(key, type(document))
        if existing is None:
            raise
        return existing
    return document


def trial_capabilities(config: SignalScoutConfig) -> dict[str, JsonValue]:
    return {
        "repositories": list(config.repositories or []),
        "network_access": config.network_access,
        "mcp_gateway_server_ids": list(config.mcp_gateway_server_ids or []),
        "write_scopes": list(config.write_scopes or []),
        "structured_output_schema": config.structured_output_schema,
    }


def assert_trial_environment_ready() -> None:
    if not getattr(settings, "SCOUT_LIVE_TRIALS_ENABLED", False):
        raise ScoutTrialLaunchError("Live scout trials are not enabled on this deployment.")
    if not getattr(settings, "SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE", False):
        raise ScoutTrialLaunchError("Live scout trials require verified gateway capture suppression.")


def load_trial_context(team_id: int, context_id: UUID | str) -> TrialContext:
    identifier = UUID(str(context_id))
    context = _read_document(_document_key(team_id, "contexts", identifier), TrialContext)
    if context is None or context.team_id != team_id or context.id != identifier:
        raise ScoutTrialLaunchError("The saved scout context was not found in this project.")
    return context


def _validate_source(context: TrialContext) -> SignalScoutConfig:
    config = SignalScoutConfig.objects.for_team(context.team_id).filter(id=context.config_id).first()
    if config is None or config.skill_name != context.skill_name:
        raise ScoutTrialLaunchError("The source scout configuration is no longer available.")
    if trial_capabilities(config) != context.capabilities:
        raise ScoutTrialLaunchError("The scout's capabilities changed. Start a new comparison.")
    team = Team.objects.get(pk=context.team_id)
    user = User.objects.filter(
        pk=context.user_id, is_active=True, organization_membership__organization_id=team.organization_id
    ).first()
    if user is None:
        raise ScoutTrialLaunchError("The operator no longer has access to this project.")
    access = UserAccessControl(user=user, team=team)
    if not access.has_project_access:
        raise ScoutTrialLaunchError("The operator no longer has access to this project.")
    for version in (None, context.skill_version):
        source = get_skill_by_name_from_db(team, context.skill_name, version)
        if source is None or not access.check_access_level_for_object(source, required_level="editor"):
            raise ScoutTrialLaunchError("Skill editor access is required for the source scout.")
    validate_scout_repositories(list(config.repositories or []), {"team": team})
    current = load_skill_for_run(team, context.skill_name)
    pinned = load_skill_for_run(team, context.skill_name, version=context.skill_version)
    if current.allowed_tools != context.allowed_tools or pinned.allowed_tools != context.allowed_tools:
        raise ScoutTrialLaunchError("The scout's tool permissions changed. Start a new comparison.")
    if pinned.body != context.skill_body or pinned.origin != context.skill_origin:
        raise ScoutTrialLaunchError("The saved source skill changed. Start a new comparison.")
    return config


def read_trial_launch(team_id: int, launch_id: UUID | str) -> TrialLaunch:
    identifier = UUID(str(launch_id))
    launch = _read_document(_document_key(team_id, "launches", identifier), TrialLaunch)
    if launch is None or launch.team_id != team_id or launch.id != identifier:
        raise ScoutTrialLaunchError("The scout trial launch was not found in this project.")
    return launch


def load_trial_launch(team_id: int, launch_id: UUID | str) -> TrialLaunch:
    launch = read_trial_launch(team_id, launch_id)
    assert_trial_environment_ready()
    context = load_trial_context(team_id, launch.context_id)
    _validate_source(context)
    if launch.config_id != context.config_id or launch.user_id != context.user_id:
        raise ScoutTrialLaunchError("The scout trial does not match its saved context.")
    return launch


def _snapshot_context(config: SignalScoutConfig, user: User, identifier: UUID, note: str) -> TrialContext:
    team = config.team
    skill = load_skill_for_run(team, config.skill_name)
    if not skill_uses_report_channel(skill.allowed_tools):
        raise ScoutTrialLaunchError("Live trials support scouts that create or edit reports.")
    if config.structured_output_schema or config.write_scopes or config.mcp_gateway_server_ids:
        raise ScoutTrialLaunchError("This scout requires writes or external tools that live trials do not support yet.")
    model_choice = resolve_scout_model(team, skill.name, str(identifier), configured_model=config.model)
    pipeline_choice = resolve_agent_runtime(team.id, STEP_SCOUT)
    adapter = model_choice.runtime_adapter if model_choice.model else pipeline_choice.runtime_adapter
    adapter = adapter or "claude"
    model = model_choice.model or pipeline_choice.model or get_default_model_for_runtime_adapter(adapter)
    if model is None or adapter not in {"claude", "codex"}:
        raise ScoutTrialLaunchError("The scout's model could not be resolved.")
    effort = model_choice.reasoning_effort if model_choice.model else pipeline_choice.reasoning_effort
    memories = (
        SignalScratchpad.objects.for_team(team.id)
        .select_related("created_by_run", "created_by_run__task_run")
        .order_by("-updated_at", "-id")
    )
    notes = SignalScoutNote.objects.for_team(team.id).select_related("created_by").order_by("-created_at", "-id")
    return TrialContext(
        id=identifier,
        team_id=team.id,
        config_id=config.id,
        user_id=user.id,
        created_at=timezone.now(),
        skill_name=skill.name,
        skill_version=skill.version,
        skill_body=skill.body,
        skill_origin=skill.origin,
        allowed_tools=skill.allowed_tools,
        capabilities=trial_capabilities(config),
        runtime_adapter=cast(Literal["claude", "codex"], adapter),
        model=model,
        reasoning_effort=effort,
        service_tier=model_choice.service_tier if model_choice.model else pipeline_choice.service_tier,
        note=note,
        memory=[cast(dict[str, JsonValue], _to_entry(row).as_dict()) for row in memories],
        notes=[cast(dict[str, JsonValue], _to_note(row).as_dict()) for row in notes],
        recent_runs=[
            cast(dict[str, JsonValue], run.as_dict())
            for run in search_recent_runs(team_id=team.id, skill_name=skill.name, limit=100)
        ],
    )


def create_trial_launch(
    *,
    config: SignalScoutConfig,
    user: User,
    launch_id: UUID,
    context_id: UUID | None = None,
    skill_body: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    note: str = "",
    variant: str = "",
) -> TrialLaunch:
    assert_trial_environment_ready()
    request_body = {
        "config_id": str(config.id),
        "user_id": user.id,
        "context_id": str(context_id) if context_id else None,
        "skill_body": skill_body,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "note": note,
        "variant": variant,
    }
    request_hash = hashlib.sha256(json.dumps(request_body, sort_keys=True).encode()).hexdigest()
    launch_key = _document_key(config.team_id, "launches", launch_id)
    existing = _read_document(launch_key, TrialLaunch)
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ScoutTrialLaunchError("This launch ID was already used with different settings.")
        return load_trial_launch(config.team_id, launch_id)
    if context_id is not None:
        context = load_trial_context(config.team_id, context_id)
        if context.config_id != config.id or context.user_id != user.id:
            raise ScoutTrialLaunchError("The saved context belongs to another scout or operator.")
        if note and note != context.note:
            raise ScoutTrialLaunchError("All variants must use the saved comparison note.")
    else:
        context_key = _document_key(config.team_id, "contexts", launch_id)
        cached_context = _read_document(context_key, TrialContext)
        context = (
            cached_context
            if cached_context is not None
            else _write_document_once(context_key, _snapshot_context(config, user, launch_id, note))
        )
    if context.config_id != config.id or context.user_id != user.id:
        raise ScoutTrialLaunchError("The saved context belongs to another scout or operator.")
    if (context_id is None or note) and note != context.note:
        raise ScoutTrialLaunchError("This saved context uses a different comparison note.")
    _validate_source(context)
    selected_model = model or context.model
    adapter = get_runtime_adapter_for_model(selected_model)
    if adapter is None:
        raise ScoutTrialLaunchError("The selected model is not supported by the scout harness.")
    selected_effort = reasoning_effort or context.reasoning_effort
    if selected_effort is None:
        raise ScoutTrialLaunchError("The source scout has no pinned effort. Supply reasoning_effort for this run.")
    model_error = get_model_access_error(selected_model, distinct_id=user.distinct_id)
    effort_error = get_reasoning_effort_error(adapter, selected_model, selected_effort)
    if model_error or effort_error:
        raise ScoutTrialLaunchError(model_error or effort_error or "The model settings are invalid.")
    launch = TrialLaunch(
        id=launch_id,
        team_id=config.team_id,
        context_id=context.id,
        config_id=config.id,
        user_id=user.id,
        created_at=timezone.now(),
        skill_name=context.skill_name,
        skill_version=context.skill_version,
        skill_body=skill_body if skill_body is not None else context.skill_body,
        runtime_adapter=cast(Literal["claude", "codex"], adapter.value),
        model=selected_model,
        reasoning_effort=selected_effort,
        service_tier=context.service_tier if selected_model == context.model else None,
        note=context.note,
        variant=variant,
        request_hash=request_hash,
    )
    saved = _write_document_once(launch_key, launch)
    if saved.request_hash != request_hash:
        raise ScoutTrialLaunchError("This launch ID was already used with different settings.")
    return saved


def bound_trial_run(team_id: int, task_id: UUID | str | None) -> SignalScoutRun | None:
    if task_id is None:
        return None
    return (
        SignalScoutRun.objects.for_team(team_id)
        .filter(task_run__task_id=task_id, metadata__scout_trial__version=1)
        .select_related("task_run")
        .first()
    )
