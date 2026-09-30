from __future__ import annotations

from dataclasses import field
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from rest_framework import exceptions

from posthog.dataclasses import frozen

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.models import SignalScoutRun
from products.signals.backend.scout_harness.run_gates import check_fleet_gates, check_spend_gates
from products.signals.backend.scout_harness.serializers import validate_scout_repositories
from products.signals.backend.scout_harness.skill_loader import load_skill_for_run
from products.signals.backend.scout_harness.trial_launch import (
    ScoutTrialLaunchError,
    _validate_source,
    assert_trial_capabilities_supported,
    assert_trial_environment_ready,
    load_trial_context,
    read_trial_launch,
    resolve_trial_source_model,
)
from products.skills.backend.api.skill_services import get_skill_by_name_from_db
from products.tasks.backend.facade.run_config import (
    RuntimeAdapter,
    get_model_access_error,
    get_models_for_runtime_adapter,
    get_supported_reasoning_efforts,
)

if TYPE_CHECKING:
    from posthog.models import User

    from products.signals.backend.models import SignalScoutConfig


@frozen
class TrialModelChoice:
    model: str
    reasoning_efforts: list[str]


@frozen
class TrialSetup:
    config_id: UUID
    skill_name: str
    skill_version: int
    skill_body: str = field(repr=False)
    ready: bool
    blocked_reason: str | None
    model: str | None
    reasoning_effort: str | None
    models: list[TrialModelChoice]


@frozen
class TrialHistoryItem:
    launch_id: UUID
    context_id: UUID
    variant: str
    model: str
    reasoning_effort: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    run_id: UUID
    task_id: UUID
    task_run_id: UUID


@frozen
class TrialHistory:
    results: list[TrialHistoryItem]
    has_more: bool


class ScoutTrialInspection:
    def __init__(self, config: SignalScoutConfig, user: User) -> None:
        self.config = config
        self.user = user

    def _check_skill_access(self, version: int | None = None) -> None:
        source = get_skill_by_name_from_db(self.config.team, self.config.skill_name, version)
        if source is None:
            raise exceptions.NotFound("The source scout skill is no longer available.")
        access = UserAccessControl(user=self.user, team=self.config.team)
        if not access.check_access_level_for_object(source, required_level="editor"):
            raise exceptions.PermissionDenied("Skill editor access is required for the source scout.")

    def setup(self, context_id: UUID | None = None) -> TrialSetup:
        self._check_skill_access()
        context = load_trial_context(self.config.team_id, context_id) if context_id else None
        if context is not None:
            if context.config_id != self.config.id or context.user_id != self.user.id:
                raise exceptions.NotFound()
            self._check_skill_access(context.skill_version)
        skill = load_skill_for_run(
            self.config.team, self.config.skill_name, version=context.skill_version if context else None
        )
        blocked_reasons: list[str] = []
        try:
            assert_trial_environment_ready()
        except ScoutTrialLaunchError as error:
            blocked_reasons.append(str(error))
        try:
            assert_trial_capabilities_supported(self.config, skill)
            validate_scout_repositories(list(self.config.repositories or []), {"team": self.config.team})
            if context is not None:
                _validate_source(context)
        except (ScoutTrialLaunchError, exceptions.ValidationError) as error:
            blocked_reasons.append(str(error))
        for rejection in (
            check_fleet_gates(self.config.team_id),
            check_spend_gates(self.config.team, capture_analytics=False),
        ):
            if rejection is not None:
                blocked_reasons.append(rejection.detail)
        model: str | None = None
        effort: str | None = None
        if context is not None:
            model = context.model
            effort = context.reasoning_effort
        else:
            try:
                runtime = resolve_trial_source_model(self.config, self.config.id)
                model = runtime.model
                effort = runtime.reasoning_effort
            except ScoutTrialLaunchError as error:
                blocked_reasons.append(str(error))
        models = [
            TrialModelChoice(
                model=identifier,
                reasoning_efforts=[effort.value for effort in get_supported_reasoning_efforts(adapter, identifier)],
            )
            for adapter in RuntimeAdapter
            for identifier in get_models_for_runtime_adapter(adapter)
            if get_model_access_error(identifier, distinct_id=self.user.distinct_id) is None
        ]
        if not models:
            blocked_reasons.append("No scout models are available for your account.")
        return TrialSetup(
            config_id=self.config.id,
            skill_name=skill.name,
            skill_version=context.skill_version if context else skill.version,
            skill_body=context.skill_body if context else skill.body,
            ready=not blocked_reasons,
            blocked_reason=" ".join(blocked_reasons) or None,
            model=model,
            reasoning_effort=effort,
            models=models,
        )

    def history(self, limit: int) -> TrialHistory:
        from products.signals.backend.facade.api import (  # noqa: PLC0415 -- the facade imports scout report tools
            is_scout_trial_task_run,
        )

        self._check_skill_access()
        runs = (
            SignalScoutRun.objects.for_team(self.config.team_id)
            .filter(
                scout_config_id=self.config.id,
                metadata__scout_trial__version=1,
                task_run__team_id=self.config.team_id,
                task_run__task__team_id=self.config.team_id,
                task_run__task__created_by=self.user,
            )
            .select_related("task_run__task")
            .order_by("-created_at", "-id")[: limit + 1]
        )
        items: list[TrialHistoryItem] = []
        for run in runs:
            if not is_scout_trial_task_run(
                team_id=self.config.team_id, task_id=run.task_run.task_id, task_run_id=run.task_run_id
            ):
                continue
            marker = (run.metadata or {})["scout_trial"]
            try:
                launch = read_trial_launch(self.config.team_id, marker["launch_id"])
            except (ScoutTrialLaunchError, ValueError):
                continue
            if launch.config_id != self.config.id or launch.user_id != self.user.id:
                continue
            if marker.get("context_id") != str(launch.context_id):
                continue
            items.append(
                TrialHistoryItem(
                    launch_id=launch.id,
                    context_id=launch.context_id,
                    variant=launch.variant,
                    model=launch.model,
                    reasoning_effort=launch.reasoning_effort,
                    status=run.task_run.status,
                    started_at=run.task_run.created_at,
                    completed_at=run.task_run.completed_at,
                    run_id=run.id,
                    task_id=run.task_run.task_id,
                    task_run_id=run.task_run_id,
                )
            )
        return TrialHistory(results=items[:limit], has_more=len(items) > limit)
