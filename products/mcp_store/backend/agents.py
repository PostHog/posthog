from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from django.conf import settings
from django.core import signing
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.models import Team
from posthog.models.scoping.manager import TeamScopeError
from posthog.models.utils import hash_key_value

from .models import MCPServiceAccount

logger = structlog.get_logger(__name__)

BuiltInAgentKey = Literal["support", "scout"]

GATEWAY_AGENT_TOKEN_PREFIX = "mcp_gw_"
GATEWAY_AGENT_TOKEN_SALT = "mcp_store.gateway_agent"
GATEWAY_AGENT_TOKEN_MAX_AGE_SECONDS = 6 * 60 * 60


@dataclass(frozen=True)
class BuiltInAgentSpec:
    key: BuiltInAgentKey
    name: str
    description: str
    handle: str


BUILT_IN_AGENTS: tuple[BuiltInAgentSpec, ...] = (
    BuiltInAgentSpec(
        key="support",
        name="Support agent",
        description="Drafts grounded replies and investigates customer support tickets.",
        handle="posthog-support",
    ),
    BuiltInAgentSpec(
        key="scout",
        name="Scout agent",
        description="Proactively investigates your product and reports useful findings.",
        handle="posthog-scout",
    ),
)

_SPEC_BY_KEY = {spec.key: spec for spec in BUILT_IN_AGENTS}
_SPEC_BY_HANDLE = {spec.handle: spec for spec in BUILT_IN_AGENTS}

_TASK_ORIGIN_TO_AGENT: dict[str, BuiltInAgentKey] = {
    "support_reply": "support",
    "signals_scout": "scout",
}
# Signal report tasks may be created through the public Tasks API, so they
# remain member-scoped instead of inheriting Scout's MCP grants.


def built_in_agent_handles() -> tuple[str, ...]:
    return tuple(spec.handle for spec in BUILT_IN_AGENTS)


def built_in_agent_key_for_task_origin(origin_product: str) -> BuiltInAgentKey | None:
    return _TASK_ORIGIN_TO_AGENT.get(origin_product)


MCP_GATEWAY_FEATURE_FLAG = "mcp-gateway"


def is_builtin_agent_enforcement_enabled(team_id: int) -> bool:
    """Per-team rollout gate for built-in agent MCP enforcement.

    Until `mcp-gateway` is enabled for the team's organization, built-in agent
    tasks keep the legacy member resolution (team-shared installations and a
    member-capable sandbox token). The Store facade and the sandbox token
    minter both key off this check — they must agree, or a legacy-resolved
    task gets a token the member proxy rejects. Fails closed to legacy so a
    flag-evaluation hiccup behaves like a not-yet-rolled-out team.

    DEBUG bypasses the flag: the analytics SDK is disabled in local dev, where
    gateway work needs enforcement on to be exercisable at all.
    """
    if settings.DEBUG:
        return True
    try:
        team = Team.objects.only("uuid", "organization_id").get(id=team_id)
        return bool(
            posthoganalytics.feature_enabled(
                MCP_GATEWAY_FEATURE_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id)},
                group_properties={"organization": {"id": str(team.organization_id)}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("mcp_gateway_enforcement_flag_check_failed", team_id=team_id)
        return False


def get_built_in_agent_spec(account: MCPServiceAccount) -> BuiltInAgentSpec | None:
    return _SPEC_BY_HANDLE.get(account.handle)


def sync_built_in_agents(team: Team) -> list[MCPServiceAccount]:
    accounts: list[MCPServiceAccount] = []
    changed: list[MCPServiceAccount] = []

    for spec in BUILT_IN_AGENTS:
        token_hash = hash_key_value(f"built-in-mcp-agent:{team.id}:{spec.key}")
        account, created = MCPServiceAccount.objects.for_team(team.id).get_or_create(
            team_id=team.id,
            token_hash=token_hash,
            defaults={
                "name": spec.name,
                "description": spec.description,
                "handle": spec.handle,
                "status": "active",
            },
        )
        if not created:
            account_changed = False
            if account.handle != spec.handle:
                account.handle = spec.handle
                account_changed = True
            if account.name != spec.name:
                account.name = spec.name
                account_changed = True
            if account.description != spec.description:
                account.description = spec.description
                account_changed = True
            if account_changed:
                account.updated_at = timezone.now()
                changed.append(account)
        accounts.append(account)

    if changed:
        MCPServiceAccount.objects.for_team(team.id).bulk_update(
            changed,
            ["name", "description", "handle", "updated_at"],
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
        # TeamScopeError: the token can outlive its team — treat a deleted team
        # like any other invalid token instead of erroring at the auth layer.
        return MCPServiceAccount.objects.for_team(team_id).get(
            id=account_id,
            handle__in=built_in_agent_handles(),
        )
    except (MCPServiceAccount.DoesNotExist, TeamScopeError, ValueError):
        return None
