"""
DRF serializers for Loops. See `products/tasks/docs/LOOPS.md` for the spec.

Presentation never imports `products.tasks.backend.models` directly (see
`products/architecture.md`): read serializers wrap the frozen DTOs from
`products.tasks.backend.facade.loops`, and write serializers resolve team-scoped
relations through facade-exposed queryset helpers, mirroring the existing pattern in
`presentation/serializers.py` (`tasks_facade.channel_queryset()` et al.).
"""

from datetime import UTC, datetime
from typing import cast
from zoneinfo import available_timezones

from django.utils import timezone as django_timezone

from croniter import croniter
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.models.integration import Integration

from products.tasks.backend.facade import loops as loops_facade
from products.tasks.backend.facade.run_config import (
    PUBLIC_REASONING_EFFORTS,
    RuntimeAdapter,
    get_default_model_for_runtime_adapter,
    get_models_for_runtime_adapter,
    get_reasoning_effort_error,
)
from products.tasks.backend.presentation.serializers import (
    TASK_RUN_SKILL_BUNDLE_FORMAT_CHOICES,
    TASK_RUN_SKILL_SOURCE_CHOICES,
)


class LoopRepositoryEntrySerializer(serializers.Serializer):
    github_integration_id = serializers.IntegerField(
        help_text="GitHub integration id this repository is accessed through."
    )
    full_name = serializers.CharField(
        max_length=255, help_text="Repository in `organization/repo` format, e.g. `posthog/posthog`."
    )

    def validate_full_name(self, value: str) -> str:
        normalized = value.strip().lower()
        parts = normalized.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise serializers.ValidationError("Repository must be in the format organization/repository")
        return normalized


class LoopBehaviorsSerializer(serializers.Serializer):
    create_prs = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether the agent may push branches and open PRs. False makes this a report-only loop.",
    )
    watch_ci = serializers.BooleanField(
        required=False, default=False, help_text="Whether to watch CI on loop-created PRs and report status."
    )
    fix_review_comments = serializers.BooleanField(
        required=False, default=False, help_text="Whether to automatically address review comments on loop-created PRs."
    )
    max_fix_iterations = serializers.IntegerField(
        required=False,
        default=loops_facade.DEFAULT_MAX_FIX_ITERATIONS,
        min_value=0,
        max_value=loops_facade.MAX_FIX_ITERATIONS_CEILING,
        help_text=f"Ceiling on automatic CI/review-comment fix iterations, capped at {loops_facade.MAX_FIX_ITERATIONS_CEILING}.",
    )


class LoopConnectorsSerializer(serializers.Serializer):
    mcp_installation_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="MCP Store installation ids (Slack, Linear, etc.) available to this loop's runs.",
    )
    posthog_mcp_scopes = serializers.ChoiceField(
        choices=loops_facade.POSTHOG_MCP_SCOPES_CHOICES,
        required=False,
        default=loops_facade.DEFAULT_POSTHOG_MCP_SCOPES,
        help_text="Scope of the PostHog MCP access injected into this loop's runs.",
    )


class LoopNotificationChannelSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False, default=False, help_text="Whether this channel is active.")
    events = serializers.ListField(
        child=serializers.ChoiceField(choices=loops_facade.NOTIFICATION_EVENTS),
        required=False,
        default=list,
        help_text=f"Event kinds this channel notifies on. One or more of: {', '.join(loops_facade.NOTIFICATION_EVENTS)}.",
    )
    params = serializers.DictField(
        required=False,
        default=dict,
        help_text="Channel-specific parameters, e.g. Slack's `integration_id` and `channel`.",
    )


class LoopNotificationsSerializer(serializers.Serializer):
    push = LoopNotificationChannelSerializer(required=False, help_text="Push notification settings.")
    email = LoopNotificationChannelSerializer(required=False, help_text="Email notification settings.")
    slack = LoopNotificationChannelSerializer(required=False, help_text="Slack notification settings.")


class LoopContextOutputsWriteSerializer(serializers.Serializer):
    post_to_feed = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether each run is filed into the context's feed as a card (sets the run's channel).",
    )
    update_context = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether each run reads and republishes the context's context.md to reflect the latest state.",
    )
    canvas_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        default=None,
        help_text="Id of a canvas in this context the loop keeps up to date each run, or null to maintain none.",
    )


class LoopContextTargetWriteSerializer(serializers.Serializer):
    folder_id = serializers.CharField(help_text="Desktop folder id of the context this loop is attached to.")
    name = serializers.CharField(max_length=128, help_text="Context (channel) name, used to file runs into its feed.")
    outputs = LoopContextOutputsWriteSerializer(
        required=False, default=dict, help_text="What the loop maintains in this context each run."
    )


def _parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # A caller can send an offset-less datetime; treat it as UTC (matching loop_service's
    # _run_at_datetime) so comparing it against an aware `now` can't raise an uncaught
    # TypeError and 500 the request instead of returning a clean validation error.
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _validate_schedule_trigger_config(config: dict, *, now: datetime) -> dict:
    run_at = config.get("run_at")
    if run_at is not None:
        parsed = _parse_iso_datetime(run_at)
        if parsed is None:
            raise serializers.ValidationError({"run_at": "Must be an ISO 8601 datetime."})
        if parsed <= now:
            raise serializers.ValidationError({"run_at": "Must be in the future."})
        return {"run_at": parsed.isoformat()}

    cron_expression = config.get("cron_expression")
    if not isinstance(cron_expression, str) or not cron_expression.strip():
        raise serializers.ValidationError({"cron_expression": "Required when `run_at` is not set."})
    normalized_cron = cron_expression.strip()
    if len(normalized_cron.split()) != 5 or not croniter.is_valid(normalized_cron):
        raise serializers.ValidationError(
            {"cron_expression": "Invalid cron expression. Use standard 5-field cron syntax (e.g. '0 9 * * 1-5')."}
        )

    timezone_name = config.get("timezone") or "UTC"
    if timezone_name not in available_timezones():
        raise serializers.ValidationError({"timezone": f"'{timezone_name}' is not a valid IANA timezone."})

    return {"cron_expression": normalized_cron, "timezone": timezone_name}


def _validate_github_trigger_config(config: dict, team_id: int) -> dict:
    github_integration_id = config.get("github_integration_id")
    if not isinstance(github_integration_id, int):
        raise serializers.ValidationError({"github_integration_id": "Required integer GitHub integration id."})
    if not loops_facade.github_integration_ids_for_team(team_id, [github_integration_id]):
        raise serializers.ValidationError({"github_integration_id": "GitHub integration not found for this team."})

    repository = config.get("repository")
    if not isinstance(repository, str) or not repository.strip():
        raise serializers.ValidationError({"repository": "Repository is required."})
    normalized_repository = repository.strip().lower()
    parts = normalized_repository.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise serializers.ValidationError({"repository": "Repository must be in the format organization/repository."})
    if not loops_facade.repository_accessible_via_integration(team_id, github_integration_id, normalized_repository):
        raise serializers.ValidationError(
            {"repository": "Repository is not accessible via the selected GitHub integration."}
        )

    events_raw = config.get("events")
    if not isinstance(events_raw, list) or not events_raw:
        raise serializers.ValidationError({"events": "At least one event is required."})
    # Agents reach for GitHub Actions shorthand like `issues.opened`; fold it into the bare
    # webhook event plus an `actions` filter instead of rejecting the trigger.
    events: list = []
    shorthand_actions: list[str] = []
    has_bare_event = False
    for item in events_raw:
        event = item
        if isinstance(item, str) and "." in item:
            base, action = item.split(".", 1)
            if base in loops_facade.ALLOWED_GITHUB_TRIGGER_EVENTS and action:
                event = base
                if action not in shorthand_actions:
                    shorthand_actions.append(action)
        else:
            has_bare_event = True
        if event not in events:
            events.append(event)
    invalid_events = sorted(set(events) - set(loops_facade.ALLOWED_GITHUB_TRIGGER_EVENTS))
    if invalid_events:
        raise serializers.ValidationError(
            {
                "events": (
                    f"Unsupported event(s): {invalid_events}. "
                    f"Allowed: {list(loops_facade.ALLOWED_GITHUB_TRIGGER_EVENTS)}, "
                    "optionally with an action suffix like 'issues.opened'."
                )
            }
        )
    # The folded `actions` filter applies to every event in the trigger, so shorthand spanning
    # several events (or mixed with bare events) would make unrequested event/action pairs fire.
    if shorthand_actions and (has_bare_event or len(events) > 1):
        raise serializers.ValidationError(
            {
                "events": (
                    "`event.action` shorthand supports a single event per trigger because the "
                    "folded `actions` filter applies to every event. Use one trigger per event, "
                    "or bare events with `filters.actions`."
                )
            }
        )

    filters_raw = config.get("filters") or {}
    if not isinstance(filters_raw, dict):
        raise serializers.ValidationError({"filters": "Filters must be an object."})
    # Accept singular keys and a bare string value too: agents (and GitHub's own webhook
    # payloads) naturally reach for `action`/`"opened"` over `actions`/`["opened"]`.
    filter_key_aliases = {"action": "actions", "branch": "branches", "label": "labels"}
    filters: dict[str, list[str]] = {}
    for raw_key, filter_value in filters_raw.items():
        key = filter_key_aliases.get(raw_key, raw_key)
        if key not in ("actions", "branches", "labels"):
            raise serializers.ValidationError(
                {"filters": f"Unsupported filter key: '{raw_key}'. Allowed: actions, branches, labels."}
            )
        values = [filter_value] if isinstance(filter_value, str) else filter_value
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise serializers.ValidationError({"filters": f"Filter '{key}' must be a string or a list of strings."})
        filters[key] = values

    if shorthand_actions:
        explicit_actions = filters.get("actions", [])
        filters["actions"] = explicit_actions + [
            action for action in shorthand_actions if action not in explicit_actions
        ]

    return {
        "github_integration_id": github_integration_id,
        "repository": normalized_repository,
        "events": events,
        "filters": filters,
    }


def _validate_api_trigger_config(config: dict) -> dict:
    if config:
        raise serializers.ValidationError("API triggers take no config.")
    return {}


class LoopTriggerWriteSerializer(serializers.Serializer):
    id = serializers.UUIDField(
        required=False,
        help_text="Existing trigger id to update in place. Omit to create a new trigger.",
    )
    type = serializers.ChoiceField(
        choices=[t.value for t in loops_facade.LoopTriggerType],
        help_text="Trigger type: `schedule` (cron or one-time), `github` (repo webhook events), or `api` (POST to `trigger/`).",
    )
    enabled = serializers.BooleanField(
        required=False, default=True, help_text="Whether this trigger is active. Disabling pauses only this trigger."
    )
    config = serializers.JSONField(
        required=False,
        default=dict,
        help_text=(
            "Trigger configuration, shape validated per `type`: schedule takes "
            "`{cron_expression, timezone}` or `{run_at}` for a one-time run; github takes "
            "`{github_integration_id, repository, events, filters}` where `events` is one or more of "
            f"{', '.join(f'`{event}`' for event in loops_facade.ALLOWED_GITHUB_TRIGGER_EVENTS)} "
            "(`event.action` shorthand like `issues.opened` is folded into an `actions` filter, one "
            "event per trigger) and "
            "`filters` takes `{actions, branches, labels}`; api takes no config."
        ),
    )

    def validate(self, attrs: dict) -> dict:
        team = self.context["team"]
        # On a partial (PATCH) update DRF skips omitted fields before the required check, so a resent
        # trigger that omits `type` reaches here without it. Fail as a clean 400, not a raw KeyError 500.
        trigger_type = attrs.get("type")
        if trigger_type is None:
            raise serializers.ValidationError({"type": "This field is required for each trigger."})
        config = attrs.get("config") or {}
        if trigger_type == loops_facade.LoopTriggerType.SCHEDULE:
            attrs["config"] = _validate_schedule_trigger_config(config, now=django_timezone.now())
        elif trigger_type == loops_facade.LoopTriggerType.GITHUB:
            attrs["config"] = _validate_github_trigger_config(config, team.id)
        elif trigger_type == loops_facade.LoopTriggerType.API:
            attrs["config"] = _validate_api_trigger_config(config)
        return attrs


class LoopWriteSerializer(serializers.Serializer):
    """Request body for creating or updating a loop. Field required/default semantics match
    the `Loop` model; partial updates only touch keys present in the payload."""

    name = serializers.CharField(max_length=400, help_text="Display name for the loop.")
    description = serializers.CharField(
        required=False, allow_blank=True, default="", help_text="Free-form description of what this loop does."
    )
    take_ownership = serializers.BooleanField(
        required=False,
        default=False,
        write_only=True,
        help_text=(
            "On a team loop, claim ownership as part of this update so you can edit identity-bearing "
            "config (instructions, model, triggers, ...) that only the owner may change. Ignored on "
            "personal loops and on create."
        ),
    )
    visibility = serializers.ChoiceField(
        choices=[v.value for v in loops_facade.LoopVisibility],
        required=False,
        default=loops_facade.LoopVisibility.PERSONAL,
        help_text="`personal` (owner-only) or `team` (visible and fireable by any team member).",
    )
    instructions = serializers.CharField(help_text="The prompt delivered to the agent on every run.")
    runtime_adapter = serializers.ChoiceField(
        choices=[adapter.value for adapter in RuntimeAdapter], help_text="Runtime adapter: 'claude' or 'codex'."
    )
    model = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text=(
            "LLM model identifier, validated against `runtime_adapter`'s catalog. "
            "Leave blank to let PostHog pick a sensible default at run time."
        ),
    )
    reasoning_effort = serializers.ChoiceField(
        choices=[effort.value for effort in PUBLIC_REASONING_EFFORTS],
        required=False,
        allow_null=True,
        help_text="Reasoning effort, validated against `runtime_adapter`/`model`'s supported set.",
    )
    repositories = serializers.ListField(
        child=LoopRepositoryEntrySerializer(),
        required=False,
        default=list,
        max_length=loops_facade.MAX_LOOP_REPOSITORIES,
        help_text=(
            f"Repositories this loop operates on, ordered. Capped at {loops_facade.MAX_LOOP_REPOSITORIES} "
            "until multi-repo execution ships. May be empty for report-only loops."
        ),
    )
    sandbox_environment = TeamScopedPrimaryKeyRelatedField(  # nosemgrep: unscoped-primary-key-related-field
        queryset=Integration.objects.none(),
        required=False,
        allow_null=True,
        help_text="Sandbox environment carrying encrypted env vars and the network allowlist into every run.",
    )
    enabled = serializers.BooleanField(
        required=False, default=True, help_text="Whether the loop's triggers are active. Pausing disables all triggers."
    )
    overlap_policy = serializers.ChoiceField(
        choices=[p.value for p in loops_facade.LoopOverlapPolicy],
        required=False,
        default=loops_facade.LoopOverlapPolicy.SKIP,
        help_text="What happens when a trigger fires while a run is already active: 'skip', 'allow', or 'cancel_previous'.",
    )
    behaviors = LoopBehaviorsSerializer(
        required=False, default=dict, help_text="PR / CI-follow-up behavior configuration."
    )
    connectors = LoopConnectorsSerializer(
        required=False, default=dict, help_text="MCP connector configuration for this loop's runs."
    )
    notifications = LoopNotificationsSerializer(
        required=False, default=dict, help_text="Per-channel notification configuration."
    )
    context_target = LoopContextTargetWriteSerializer(
        required=False,
        allow_null=True,
        help_text=(
            "Context (channel) this loop is attached to, or null to detach. Drives feed placement "
            "and the context.md / canvas it keeps up to date."
        ),
    )
    triggers = LoopTriggerWriteSerializer(
        many=True,
        required=False,
        # drf-stubs types many=True against the child serializer and misses ListSerializer's max_length
        max_length=loops_facade.MAX_TRIGGERS_PER_LOOP,  # type: ignore[call-arg]
        help_text=(
            "Full desired trigger list, id-stable: entries with a matching `id` are updated in place, "
            "entries without one are created, and existing triggers absent from this list are deleted. "
            f"Omit the field entirely to leave triggers untouched. At most {loops_facade.MAX_TRIGGERS_PER_LOOP} "
            "triggers per loop."
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cast(
            TeamScopedPrimaryKeyRelatedField, self.fields["sandbox_environment"]
        ).queryset = loops_facade.sandbox_environment_queryset()

    def validate_repositories(self, value: list[dict]) -> list[dict]:
        team = self.context["team"]
        # A partial update can skip a nested entry's required `github_integration_id`; guard before
        # indexing so it's a 400, not a KeyError 500.
        if any(entry.get("github_integration_id") is None for entry in value):
            raise serializers.ValidationError("Each repository requires a `github_integration_id`.")
        integration_ids = {entry["github_integration_id"] for entry in value}
        if not integration_ids:
            return value
        team_integration_ids = loops_facade.team_github_integration_ids(team.id)
        missing = sorted(integration_ids - team_integration_ids)
        if missing:
            if not team_integration_ids:
                raise serializers.ValidationError(
                    "This project has no GitHub integration. Connect GitHub for this project, "
                    "or build a report-only loop with no repositories."
                )
            raise serializers.ValidationError(
                f"GitHub integration(s) not found for this project: {missing}. "
                f"This project's GitHub integration ids are: {sorted(team_integration_ids)}."
            )
        return value

    def validate(self, attrs: dict) -> dict:
        runtime_adapter = attrs.get("runtime_adapter")
        model = attrs.get("model")
        if runtime_adapter is not None and model:
            allowed_models = get_models_for_runtime_adapter(runtime_adapter)
            if allowed_models and model not in allowed_models:
                raise serializers.ValidationError(
                    {"model": f"'{model}' is not a supported model for runtime_adapter '{runtime_adapter}'."}
                )

        reasoning_effort = attrs.get("reasoning_effort")
        if runtime_adapter is not None and reasoning_effort is not None:
            # A blank model means "PostHog picks at run time", so the effort is
            # validated against the model that would actually run.
            effective_model = model or get_default_model_for_runtime_adapter(runtime_adapter)
            if effective_model:
                error = get_reasoning_effort_error(runtime_adapter, effective_model, reasoning_effort)
                if error:
                    raise serializers.ValidationError({"reasoning_effort": error})

        if "sandbox_environment" in attrs:
            sandbox_environment = attrs.pop("sandbox_environment")
            attrs["sandbox_environment_id"] = sandbox_environment.id if sandbox_environment is not None else None

        connectors = attrs.get("connectors")
        installation_ids = (connectors or {}).get("mcp_installation_ids") if connectors else None
        if installation_ids:
            valid_ids = loops_facade.active_mcp_installation_ids(self.context["team"].id, self.context.get("user_id"))
            invalid = sorted(set(installation_ids) - valid_ids)
            if invalid:
                raise serializers.ValidationError(
                    {"connectors": f"MCP installation(s) not found or inactive: {invalid}"}
                )

        context_target = attrs.get("context_target")
        if context_target:
            team_id = self.context["team"].id
            if not loops_facade.desktop_folder_exists(team_id, context_target.get("folder_id")):
                raise serializers.ValidationError({"context_target": "Context folder not found for this team."})
            canvas_id = (context_target.get("outputs") or {}).get("canvas_id")
            if canvas_id and not loops_facade.desktop_canvas_exists(team_id, canvas_id):
                raise serializers.ValidationError({"context_target": "Canvas not found in this team."})

        return attrs


class LoopTriggerSerializer(DataclassSerializer):
    """Read response for a single loop trigger."""

    class Meta:
        dataclass = loops_facade.LoopTriggerDTO
        fields = [
            "id",
            "loop_id",
            "type",
            "enabled",
            "config",
            "schedule_sync_status",
            "last_fired_at",
            "created_at",
            "updated_at",
        ]


class LoopBehaviorsResponseSerializer(DataclassSerializer):
    class Meta:
        dataclass = loops_facade.LoopBehaviorsDTO


class LoopConnectorsResponseSerializer(DataclassSerializer):
    class Meta:
        dataclass = loops_facade.LoopConnectorsDTO


class LoopNotificationChannelResponseSerializer(DataclassSerializer):
    class Meta:
        dataclass = loops_facade.LoopNotificationChannelDTO


class LoopNotificationsResponseSerializer(DataclassSerializer):
    push = LoopNotificationChannelResponseSerializer()
    email = LoopNotificationChannelResponseSerializer()
    slack = LoopNotificationChannelResponseSerializer()

    class Meta:
        dataclass = loops_facade.LoopNotificationsDTO


class LoopContextOutputsResponseSerializer(DataclassSerializer):
    class Meta:
        dataclass = loops_facade.LoopContextOutputsDTO


class LoopContextTargetResponseSerializer(DataclassSerializer):
    outputs = LoopContextOutputsResponseSerializer(help_text="What the loop maintains in this context each run.")

    class Meta:
        dataclass = loops_facade.LoopContextTargetDTO


class LoopRepositoryEntryResponseSerializer(DataclassSerializer):
    class Meta:
        dataclass = loops_facade.LoopRepositoryEntryDTO


class LoopSkillBundleResponseSerializer(DataclassSerializer):
    class Meta:
        dataclass = loops_facade.LoopSkillBundleDTO


class LoopSerializer(DataclassSerializer):
    """Detail/create/update response for a loop, including its triggers."""

    repositories = LoopRepositoryEntryResponseSerializer(many=True, help_text="Repositories this loop operates on.")
    behaviors = LoopBehaviorsResponseSerializer(help_text="PR / CI-follow-up behavior configuration.")
    connectors = LoopConnectorsResponseSerializer(help_text="MCP connector configuration for this loop's runs.")
    notifications = LoopNotificationsResponseSerializer(help_text="Per-channel notification configuration.")
    context_target = LoopContextTargetResponseSerializer(
        allow_null=True, required=False, help_text="Context this loop is attached to, or null when unattached."
    )
    triggers = LoopTriggerSerializer(many=True, help_text="Triggers attached to this loop.")
    skill_bundles = LoopSkillBundleResponseSerializer(
        many=True, help_text="Skill bundles attached to this loop, seeded into every fired run."
    )

    class Meta:
        dataclass = loops_facade.LoopDTO
        fields = [
            "id",
            "team_id",
            "created_by_id",
            "name",
            "description",
            "visibility",
            "instructions",
            "runtime_adapter",
            "model",
            "reasoning_effort",
            "repositories",
            "sandbox_environment_id",
            "enabled",
            "disabled_reason",
            "overlap_policy",
            "behaviors",
            "connectors",
            "notifications",
            "context_target",
            "internal",
            "origin_product",
            "last_run_at",
            "last_run_status",
            "last_error",
            "consecutive_failures",
            "created_at",
            "updated_at",
            "triggers",
            "skill_bundles",
        ]


class LoopRunSerializer(DataclassSerializer):
    """A single entry in a loop's run history."""

    class Meta:
        dataclass = loops_facade.LoopRunDTO
        fields = [
            "id",
            "task_id",
            "loop_trigger_id",
            "status",
            "environment",
            "branch",
            "error_message",
            "output",
            "created_at",
            "completed_at",
        ]


class LoopRunPageSerializer(serializers.Serializer):
    results = LoopRunSerializer(many=True, help_text="Run history entries, newest first.")
    next_cursor = serializers.CharField(
        allow_null=True, help_text="Opaque cursor for the next page, or null when there are no more results."
    )


class LoopRunsQuerySerializer(serializers.Serializer):
    cursor = serializers.CharField(
        required=False, help_text="Opaque pagination cursor from a previous response's `next_cursor`."
    )
    limit = serializers.IntegerField(
        required=False,
        default=loops_facade.DEFAULT_LOOP_RUN_PAGE_SIZE,
        min_value=1,
        max_value=loops_facade.MAX_LOOP_RUN_PAGE_SIZE,
        help_text=f"Max results per page (default {loops_facade.DEFAULT_LOOP_RUN_PAGE_SIZE}, max {loops_facade.MAX_LOOP_RUN_PAGE_SIZE}).",
    )


class LoopPreviewRequestSerializer(serializers.Serializer):
    trigger_type = serializers.ChoiceField(
        choices=[t.value for t in loops_facade.LoopTriggerType],
        required=False,
        default=loops_facade.LoopTriggerType.SCHEDULE,
        help_text="Trigger type to simulate. Defaults to a synthetic schedule fire.",
    )
    payload = serializers.JSONField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Sample trigger payload, e.g. a GitHub webhook body or an API trigger body, to render into context.",
    )


class LoopPreviewSerializer(DataclassSerializer):
    class Meta:
        dataclass = loops_facade.LoopPreviewDTO


class LoopSkillBundleUploadSerializer(serializers.Serializer):
    """One zipped local skill in a skill-bundle replace request."""

    file_name = serializers.CharField(
        allow_blank=False, max_length=255, help_text="File name for the stored bundle, e.g. `my-skill.zip`."
    )
    skill_name = serializers.CharField(
        allow_blank=False, max_length=255, help_text="Name of the skill inside the bundle."
    )
    skill_source = serializers.ChoiceField(
        choices=TASK_RUN_SKILL_SOURCE_CHOICES, help_text="Local source the bundle was built from, such as user or repo."
    )
    content_sha256 = serializers.RegexField(
        regex=r"^[a-f0-9]{64}$", help_text="SHA-256 hex digest of the bundle bytes."
    )
    bundle_format = serializers.ChoiceField(
        choices=TASK_RUN_SKILL_BUNDLE_FORMAT_CHOICES, help_text="Archive format used for the bundle."
    )
    content_base64 = serializers.CharField(allow_blank=False, help_text="Base64-encoded bundle bytes.")


class LoopSkillBundlesWriteSerializer(serializers.Serializer):
    """Request body for replacing a loop's attached skill bundles wholesale. Send an empty
    list to detach every skill."""

    bundles = LoopSkillBundleUploadSerializer(many=True, allow_empty=True)


class LoopFireRunSerializer(DataclassSerializer):
    """Response for a manual (`run/`) or external (`trigger/`) fire."""

    reason = serializers.ChoiceField(
        choices=[
            "created",
            "deduped",
            "overlap_skipped",
            "rate_capped",
            "team_rate_capped",
            "disabled",
            "gate_blocked",
            "owner_inactive",
            "owner_changed",
        ],
        help_text="Outcome of the fire attempt.",
    )
    task_id = serializers.UUIDField(allow_null=True, help_text="Id of the created task, when `created` is true.")
    task_run_id = serializers.UUIDField(
        allow_null=True, help_text="Id of the created task run, when `created` is true."
    )

    class Meta:
        dataclass = loops_facade.LoopFireResult
        fields = ["created", "reason", "task_id", "task_run_id"]
