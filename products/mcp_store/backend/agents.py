from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from django.core import signing
from django.utils import timezone

import structlog

from posthog.models import Team
from posthog.models.utils import hash_key_value

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

from .models import MCPServiceAccount

logger = structlog.get_logger(__name__)

BuiltInAgentKey = Literal["support", "scout", "posthog_ai"]

GATEWAY_AGENT_TOKEN_PREFIX = "mcp_gw_"
GATEWAY_AGENT_TOKEN_SALT = "mcp_store.gateway_agent"
GATEWAY_AGENT_TOKEN_MAX_AGE_SECONDS = 6 * 60 * 60


@dataclass(frozen=True)
class BuiltInAgentSpec:
    key: BuiltInAgentKey
    name: str
    description: str
    handle: str


@dataclass(frozen=True)
class AgentProductAvailability:
    enabled: bool
    disabled_reason: str


BUILT_IN_AGENTS: tuple[BuiltInAgentSpec, ...] = (
    BuiltInAgentSpec(
        key="support",
        name="Support agent",
        description="Drafts grounded replies and investigates customer support tickets.",
        handle="svc-posthog-support",
    ),
    BuiltInAgentSpec(
        key="scout",
        name="Scout agent",
        description="Proactively investigates your product and reports useful findings.",
        handle="svc-posthog-scout",
    ),
    BuiltInAgentSpec(
        key="posthog_ai",
        name="PostHog AI",
        description="Helps your team analyze data and make changes across PostHog.",
        handle="svc-posthog-ai",
    ),
)

_SPEC_BY_KEY = {spec.key: spec for spec in BUILT_IN_AGENTS}
_SPEC_BY_HANDLE = {spec.handle: spec for spec in BUILT_IN_AGENTS}

_TASK_ORIGIN_TO_AGENT: dict[str, BuiltInAgentKey] = {
    "support_reply": "support",
    "signals_scout": "scout",
    "posthog_ai": "posthog_ai",
}
# Signal report tasks may be created through the public Tasks API, so they
# remain member-scoped instead of inheriting Scout's MCP grants.


def built_in_agent_handles() -> tuple[str, ...]:
    return tuple(spec.handle for spec in BUILT_IN_AGENTS)


def built_in_agent_key_for_task_origin(origin_product: str) -> BuiltInAgentKey | None:
    return _TASK_ORIGIN_TO_AGENT.get(origin_product)


def get_built_in_agent_spec(account: MCPServiceAccount) -> BuiltInAgentSpec | None:
    return _SPEC_BY_HANDLE.get(account.handle)


def get_agent_product_availability(team: Team, agent_key: BuiltInAgentKey) -> AgentProductAvailability:
    if not team.organization.is_ai_data_processing_approved:
        return AgentProductAvailability(
            enabled=False,
            disabled_reason="Approve AI data processing for this organization to use this agent.",
        )

    if agent_key == "support":
        if not team.conversations_enabled:
            return AgentProductAvailability(
                enabled=False,
                disabled_reason="Enable Support before using the Support agent.",
            )
        if not (team.conversations_settings or {}).get("ai_suggestions_enabled", False):
            return AgentProductAvailability(
                enabled=False,
                disabled_reason="Enable the AI agent in Support settings first.",
            )

    quota_resource = {
        "scout": QuotaResource.SIGNALS_CREDITS,
        "posthog_ai": QuotaResource.AI_CREDITS,
    }.get(agent_key)
    quota_limited = False
    if quota_resource is not None:
        try:
            quota_limited = is_team_limited(
                team.api_token,
                quota_resource,
                QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
            )
        except Exception:
            logger.warning(
                "mcp_builtin_agent_quota_check_failed_open",
                team_id=team.id,
                agent_key=agent_key,
                exc_info=True,
            )
    if quota_limited:
        product_name = "Signals" if agent_key == "scout" else "PostHog AI"
        return AgentProductAvailability(
            enabled=False,
            disabled_reason=f"Increase your {product_name} credits limit in Billing to use this agent.",
        )

    return AgentProductAvailability(enabled=True, disabled_reason="")


def sync_built_in_agents(team: Team) -> list[MCPServiceAccount]:
    accounts: list[MCPServiceAccount] = []
    changed: list[MCPServiceAccount] = []

    for spec in BUILT_IN_AGENTS:
        availability = get_agent_product_availability(team, spec.key)
        account, created = MCPServiceAccount.objects.for_team(team.id).get_or_create(
            team_id=team.id,
            handle=spec.handle,
            defaults={
                "name": spec.name,
                "description": spec.description,
                "status": "active" if availability.enabled else "paused",
                "token_hash": hash_key_value(f"built-in-mcp-agent:{team.id}:{spec.key}"),
            },
        )
        if not created:
            account_changed = False
            if account.name != spec.name:
                account.name = spec.name
                account_changed = True
            if account.description != spec.description:
                account.description = spec.description
                account_changed = True
            if not availability.enabled and account.status != "paused":
                account.status = "paused"
                account_changed = True
            if account_changed:
                account.updated_at = timezone.now()
                changed.append(account)
        accounts.append(account)

    if changed:
        MCPServiceAccount.objects.for_team(team.id).bulk_update(
            changed,
            ["name", "description", "status", "updated_at"],
        )

    return accounts


def get_built_in_agent(team_id: int, agent_key: str) -> MCPServiceAccount | None:
    spec = next((candidate for candidate in BUILT_IN_AGENTS if candidate.key == agent_key), None)
    if spec is None:
        return None
    try:
        team = Team.objects.select_related("organization").get(id=team_id)
    except Team.DoesNotExist:
        return None
    return next(account for account in sync_built_in_agents(team) if account.handle == spec.handle)


def create_gateway_agent_token(account: MCPServiceAccount) -> str:
    payload = {"service_account_id": str(account.id), "team_id": account.team_id}
    return GATEWAY_AGENT_TOKEN_PREFIX + signing.dumps(payload, salt=GATEWAY_AGENT_TOKEN_SALT)


def resolve_gateway_agent_token(token: str) -> MCPServiceAccount | None:
    if not token.startswith(GATEWAY_AGENT_TOKEN_PREFIX):
        return None
    signed_value = token.removeprefix(GATEWAY_AGENT_TOKEN_PREFIX)
    try:
        payload = signing.loads(
            signed_value,
            salt=GATEWAY_AGENT_TOKEN_SALT,
            max_age=GATEWAY_AGENT_TOKEN_MAX_AGE_SECONDS,
        )
    except signing.BadSignature:
        return None
    if not isinstance(payload, dict):
        return None
    account_id = payload.get("service_account_id")
    team_id = payload.get("team_id")
    if not account_id or not isinstance(team_id, int):
        return None
    try:
        account = (
            MCPServiceAccount.objects.unscoped()
            .select_related("team__organization")
            .get(
                id=account_id,
                team_id=team_id,
                handle__in=built_in_agent_handles(),
            )
        )
    except (MCPServiceAccount.DoesNotExist, ValueError):
        return None
    spec = get_built_in_agent_spec(account)
    if spec is None or not get_agent_product_availability(account.team, spec.key).enabled:
        return None
    return account
