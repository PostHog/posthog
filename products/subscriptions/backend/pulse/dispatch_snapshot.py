"""Build the immutable, server-authorized Pulse snapshot for scheduled AI deliveries."""

import json
from hashlib import sha256

from django.conf import settings

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.storage import object_storage

from products.exports.backend.facade.api import subscription_snapshot_contexts_are_authorized
from products.subscriptions.backend.models import ProactiveSubscriptionConfig, RepositoryGrant
from products.subscriptions.backend.pulse.repository_grants import (
    repository_grant_authorization_is_live,
    repository_grants_authorizations_are_live,
)
from products.subscriptions.backend.pulse.services import MAX_SNAPSHOT_CONTEXTS, MAX_SNAPSHOT_PROMPT_CHARS
from products.subscriptions.backend.pulse.temporal.inputs import ProactiveDispatchSnapshot

MAX_SNAPSHOT_BYTES = 32 * 1024
MAX_DISPATCH_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_DISPATCH_MANIFEST_ENTRY_BYTES = 4 * 1024
DISPATCH_MANIFEST_PREFIX = "subscriptions/pulse/dispatch-manifests/v1/"
MAX_WALL_CLOCK_SECONDS = 60 * 60
MAX_FINALIZATION_MARGIN_SECONDS = 15 * 60
DEFAULT_WALL_CLOCK_SECONDS = 60 * 60
DEFAULT_FINALIZATION_MARGIN_SECONDS = 5 * 60
DEFAULT_AGENT_CONTEXT_WINDOW_TOKENS = 200_000
SUPPORTED_AGENT_CONTEXT_WINDOW_TOKENS = frozenset({200_000, 1_000_000})


@frozen
class ScheduledPulseEligibilityInput:
    team_id: int
    subscription_id: int
    prompt: str
    contexts: list[dict[str, int]]
    actor_id: int
    integration_id: int | None
    contexts_authorized: bool | None = None


def build_scheduled_proactive_dispatch_snapshots(
    inputs: list[ScheduledPulseEligibilityInput],
) -> dict[int, ProactiveDispatchSnapshot | None]:
    """Build a batch of scheduled snapshots without exposing Subscription ORM to callers."""
    snapshots: dict[int, ProactiveDispatchSnapshot | None] = {input.subscription_id: None for input in inputs}
    if not inputs or not getattr(settings, "PULSE_PROACTIVE_ENABLED", False):
        return snapshots
    subscription_ids = {input.subscription_id for input in inputs}
    team_ids = {input.team_id for input in inputs}
    actor_ids = {input.actor_id for input in inputs}
    configs_by_subscription_id = {
        config.subscription_id: config
        for config in ProactiveSubscriptionConfig.all_teams.filter(subscription_id__in=subscription_ids).select_related(
            "repository_grant"
        )
    }
    inputs_by_subscription_id = {input.subscription_id: input for input in inputs}
    teams_by_id = Team.objects.filter(id__in=team_ids).in_bulk()
    actors_by_id = User.objects.filter(id__in=actor_ids, is_active=True).in_bulk()
    grants = [
        config.repository_grant
        for config in configs_by_subscription_id.values()
        if (
            config.create_draft_pr
            and config.repository_grant is not None
            and inputs_by_subscription_id[config.subscription_id].contexts_authorized is not False
        )
    ]
    live_authorizations = repository_grants_authorizations_are_live(grants)
    for input in inputs:
        config = configs_by_subscription_id.get(input.subscription_id)
        grant = config.repository_grant if config is not None else None
        snapshots[input.subscription_id] = build_scheduled_proactive_dispatch_snapshot(
            input,
            team=teams_by_id.get(input.team_id),
            actor=actors_by_id.get(input.actor_id),
            config=config,
            config_preloaded=True,
            grant=grant,
            grant_preloaded=True,
            grant_authorized=live_authorizations.get(grant.id) if grant is not None else None,
            contexts_authorized=input.contexts_authorized,
        )
    return snapshots


def build_scheduled_proactive_dispatch_manifest(inputs: list[ScheduledPulseEligibilityInput]) -> str | None:
    """Persist one schedule-wide snapshot map as immutable per-subscription entries.

    Authorization stays deduplicated across the whole batch, while each child
    reads only its own small entry and Temporal carries one shared reference.
    """
    snapshots = build_scheduled_proactive_dispatch_snapshots(inputs)
    inputs_by_subscription_id = {input.subscription_id: input for input in inputs}
    serialized_snapshots = {
        str(subscription_id): {
            "team_id": inputs_by_subscription_id[subscription_id].team_id,
            "version": snapshot.version,
            "enabled": snapshot.enabled,
            "config_snapshot_ref": snapshot.config_snapshot_ref,
            "wall_clock_budget_seconds": snapshot.wall_clock_budget_seconds,
            "finalization_margin_seconds": snapshot.finalization_margin_seconds,
        }
        for subscription_id, snapshot in snapshots.items()
        if snapshot is not None
    }
    if not serialized_snapshots:
        return None
    encoded = json.dumps(
        {"version": 1, "snapshots": serialized_snapshots}, sort_keys=True, separators=(",", ":")
    ).encode()
    if len(encoded) > MAX_DISPATCH_MANIFEST_BYTES:
        return None
    digest = sha256(encoded).hexdigest()
    reference = f"{DISPATCH_MANIFEST_PREFIX}{digest}"
    for raw_subscription_id, raw_snapshot in serialized_snapshots.items():
        subscription_id = int(raw_subscription_id)
        entry = json.dumps(
            {
                "version": 1,
                "manifest_digest": digest,
                "team_id": raw_snapshot["team_id"],
                "subscription_id": subscription_id,
                "snapshot": raw_snapshot,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if len(entry) > MAX_DISPATCH_MANIFEST_ENTRY_BYTES:
            return None
        entry_ref = f"{reference}/{subscription_id}.json"
        existing = object_storage.read_bytes(entry_ref, bucket=settings.OBJECT_STORAGE_BUCKET, missing_ok=True)
        if existing is None:
            object_storage.write(
                entry_ref,
                entry,
                extras={"ContentType": "application/json"},
                bucket=settings.OBJECT_STORAGE_BUCKET,
            )
        elif existing != entry:
            return None
    return reference


def resolve_scheduled_proactive_dispatch_manifest(
    manifest_ref: str, team_id: int, subscription_id: int
) -> ProactiveDispatchSnapshot | None:
    """Resolve one small subscription entry from a content-addressed schedule manifest."""
    if not manifest_ref.startswith(DISPATCH_MANIFEST_PREFIX):
        return None
    expected_digest = manifest_ref[len(DISPATCH_MANIFEST_PREFIX) :]
    if len(expected_digest) != 64 or any(character not in "0123456789abcdef" for character in expected_digest):
        return None
    entry_ref = f"{manifest_ref}/{subscription_id}.json"
    encoded = object_storage.read_bytes(entry_ref, bucket=settings.OBJECT_STORAGE_BUCKET, missing_ok=True)
    if encoded is None or len(encoded) > MAX_DISPATCH_MANIFEST_ENTRY_BYTES:
        return None
    try:
        entry = json.loads(encoded)
    except (TypeError, ValueError):
        return None
    if (
        not isinstance(entry, dict)
        or entry.get("version") != 1
        or entry.get("manifest_digest") != expected_digest
        or entry.get("team_id") != team_id
        or entry.get("subscription_id") != subscription_id
    ):
        return None
    raw_snapshot = entry.get("snapshot")
    if not isinstance(raw_snapshot, dict) or raw_snapshot.get("team_id") != team_id:
        return None
    version = raw_snapshot.get("version")
    enabled = raw_snapshot.get("enabled")
    config_snapshot_ref = raw_snapshot.get("config_snapshot_ref")
    wall_clock_budget_seconds = raw_snapshot.get("wall_clock_budget_seconds")
    finalization_margin_seconds = raw_snapshot.get("finalization_margin_seconds")
    if (
        type(version) is not int
        or version != 1
        or type(enabled) is not bool
        or not isinstance(config_snapshot_ref, str)
        or not config_snapshot_ref.startswith(f"subscriptions/pulse/dispatch-snapshots/v1/{team_id}/{subscription_id}/")
        or type(wall_clock_budget_seconds) is not int
        or wall_clock_budget_seconds < 0
        or type(finalization_margin_seconds) is not int
        or finalization_margin_seconds < 0
    ):
        return None
    return ProactiveDispatchSnapshot(
        version=version,
        enabled=enabled,
        config_snapshot_ref=config_snapshot_ref,
        wall_clock_budget_seconds=wall_clock_budget_seconds,
        finalization_margin_seconds=finalization_margin_seconds,
    )


def build_scheduled_proactive_dispatch_snapshot(
    input: ScheduledPulseEligibilityInput,
    *,
    team: Team | None = None,
    actor: User | None = None,
    config: ProactiveSubscriptionConfig | None = None,
    config_preloaded: bool = False,
    grant: RepositoryGrant | None = None,
    grant_preloaded: bool = False,
    grant_authorized: bool | None = None,
    contexts_authorized: bool | None = None,
) -> ProactiveDispatchSnapshot | None:
    if not getattr(settings, "PULSE_PROACTIVE_ENABLED", False):
        return None
    if not input.prompt or len(input.prompt) > MAX_SNAPSHOT_PROMPT_CHARS or len(input.contexts) > MAX_SNAPSHOT_CONTEXTS:
        return None
    team = team or Team.objects.filter(id=input.team_id).first()
    actor = actor or User.objects.filter(id=input.actor_id, is_active=True).first()
    if team is None or actor is None:
        return None
    if config_preloaded and (team.id != input.team_id or actor.id != input.actor_id or not actor.is_active):
        return None
    if contexts_authorized is None:
        contexts_authorized = subscription_snapshot_contexts_are_authorized(
            team=team,
            user=actor,
            subscription_id=input.subscription_id,
            contexts=input.contexts,
        )
    if not contexts_authorized:
        return None
    if config is None and not config_preloaded:
        config = (
            ProactiveSubscriptionConfig.objects.for_team(input.team_id)
            .filter(subscription_id=input.subscription_id)
            .first()
        )
    if config is None or not config.enabled:
        return None
    if config_preloaded and (config.team_id != input.team_id or config.subscription_id != input.subscription_id):
        return None
    grant = _eligible_grant(
        input=input,
        config=config,
        grant=grant,
        preloaded=grant_preloaded,
        authorization_is_live=grant_authorized,
    )
    if config.create_draft_pr and grant is None:
        return None
    wall_clock_seconds = _bounded_setting(
        "PULSE_WALL_CLOCK_SECONDS",
        DEFAULT_WALL_CLOCK_SECONDS,
        MAX_WALL_CLOCK_SECONDS,
        minimum=60,
    )
    finalization_margin_seconds = min(
        _bounded_setting(
            "PULSE_FINALIZATION_MARGIN_SECONDS",
            DEFAULT_FINALIZATION_MARGIN_SECONDS,
            MAX_FINALIZATION_MARGIN_SECONDS,
            minimum=1,
        ),
        wall_clock_seconds - 1,
    )
    snapshot = {
        "version": 1,
        "prompt": input.prompt,
        "contexts": input.contexts,
        "actor_id": input.actor_id,
        "integration_id": input.integration_id,
        "repository": config.repository,
        "repository_grant_id": str(grant.id) if grant is not None else None,
        "repository_grant": {
            "id": str(grant.id),
            "config_id": str(grant.config_id),
            "authorizer_id": grant.authorizer_id,
            "automation_owner_id": grant.automation_owner_id,
            "repository": grant.repository,
            "integration_id": grant.integration_id,
            "installation_id": grant.repository_installation_id,
            "grant_version": grant.grant_version,
            "capabilities": grant.capabilities,
        }
        if grant is not None
        else None,
        "public_research_enabled": config.public_research_enabled,
        "repository_grant_version": str(grant.grant_version) if grant is not None else None,
        "repository_installation_id": grant.repository_installation_id if grant is not None else None,
        "automation_owner_id": grant.automation_owner_id if grant is not None else None,
        "flags": {
            "allow_draft_pr": bool(config.create_draft_pr and getattr(settings, "PULSE_DRAFT_PR_ENABLED", False)),
            "allow_experiment_draft": bool(getattr(settings, "PULSE_EXPERIMENT_DRAFT_ENABLED", False)),
            "allow_public_research": config.public_research_enabled
            and bool(getattr(settings, "PULSE_PUBLIC_RESEARCH_ENABLED", False))
            and bool(settings.FIRECRAWL_API_KEY),
            "allow_outcome_readouts": bool(getattr(settings, "PULSE_OUTCOME_READOUT_ENABLED", False)),
        },
        "limits": {
            "max_runtime_seconds": wall_clock_seconds,
            "max_actions": _bounded_setting("PULSE_MAX_ACTIONS", 3, 3, minimum=1),
            "max_tool_calls": _bounded_setting("PULSE_MAX_TOOL_CALLS", 20, 20, minimum=1),
            "max_public_research_calls": _bounded_setting("PULSE_MAX_PUBLIC_RESEARCH_CALLS", 3, 3, minimum=0),
            "max_agent_context_tokens": _agent_context_window_tokens(),
            "max_due_readouts": _bounded_setting("PULSE_MAX_DUE_READOUTS_PER_DELIVERY", 3, 10, minimum=1),
            "outcome_memory_max_rows": _bounded_setting("PULSE_OUTCOME_MEMORY_MAX_ROWS", 50, 100, minimum=1),
            "outcome_memory_max_bytes": _bounded_setting(
                "PULSE_OUTCOME_MEMORY_MAX_BYTES", 16 * 1024, 32 * 1024, minimum=1
            ),
        },
    }
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        return None
    digest = sha256(encoded).hexdigest()
    reference = f"subscriptions/pulse/dispatch-snapshots/v1/{input.team_id}/{input.subscription_id}/{digest}.json"
    existing = object_storage.read_bytes(reference, bucket=settings.OBJECT_STORAGE_BUCKET, missing_ok=True)
    if existing is None:
        object_storage.write(
            reference,
            encoded,
            extras={"ContentType": "application/json"},
            bucket=settings.OBJECT_STORAGE_BUCKET,
        )
    elif existing != encoded:
        return None
    return ProactiveDispatchSnapshot(
        version=1,
        enabled=True,
        config_snapshot_ref=reference,
        wall_clock_budget_seconds=wall_clock_seconds,
        finalization_margin_seconds=finalization_margin_seconds,
    )


def _eligible_grant(
    *,
    input: ScheduledPulseEligibilityInput,
    config: ProactiveSubscriptionConfig,
    grant: RepositoryGrant | None = None,
    preloaded: bool = False,
    authorization_is_live: bool | None = None,
) -> RepositoryGrant | None:
    if config.repository_grant_id is None or not config.repository:
        return None
    if grant is None and not preloaded:
        grant = RepositoryGrant.objects.for_team(input.team_id).filter(id=config.repository_grant_id).first()
    repository = config.repository.strip().lower()
    if (
        grant is None
        or not grant.active
        or grant.revoked_at is not None
        or grant.config_id != config.id
        or grant.repository.strip().lower() != repository
        or not grant.repository_installation_id
        or not isinstance(grant.capabilities, dict)
        or grant.capabilities.get("draft_pr") is not True
        or not (
            authorization_is_live
            if authorization_is_live is not None
            else repository_grant_authorization_is_live(team_id=input.team_id, grant=grant)
        )
    ):
        return None
    return grant


def _agent_context_window_tokens() -> int:
    """Return an agent input-context cap, never a total token-spend budget."""
    value = getattr(settings, "PULSE_MAX_AGENT_CONTEXT_TOKENS", DEFAULT_AGENT_CONTEXT_WINDOW_TOKENS)
    if type(value) is not int or value not in SUPPORTED_AGENT_CONTEXT_WINDOW_TOKENS:
        return DEFAULT_AGENT_CONTEXT_WINDOW_TOKENS
    return value


def _bounded_setting(name: str, default: int, cap: int, *, minimum: int) -> int:
    value = getattr(settings, name, default)
    if not isinstance(value, int) or isinstance(value, bool):
        return default
    return min(cap, max(minimum, value))
