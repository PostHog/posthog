"""Gateway policy engine.

Resolves the effective state of one tool for one caller. Team policy is a
ceiling: a caller may choose the same state or a more restrictive state, but
can never make a tool more permissive than the team allows.

1. Org rules — enabled team guardrails; a match locks the state.
2. The stricter of the caller's own choice and the team ceiling. The caller's
   choice comes from its scope row, or for members from the legacy
   per-installation state. The ceiling comes from the explicit team row, then
   the audience preset.
3. `needs_approval` — freshly discovered tools are opt-in when neither side
   has made a choice.

Every consumer (member proxy, agent proxy, Max, the gateway UI) resolves
through this module so their answers can't drift apart.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any, Literal
from uuid import UUID

from django.db.models import Q

from posthog.models.scoping.manager import resolve_effective_team_id

from .models import MCPGatewayServer, MCPOrgRule, MCPServerInstallation, MCPToolPolicy, TeamMCPGatewayConfig

# What tool sync stamps on every freshly discovered row (see tools.py). Only
# members have this legacy layer, so a row still sitting at the sync default
# would invent a member preference that no one chose — and because a caller's
# own choice beats a laxer ceiling, that phantom undercuts the team baseline.
# The result was incoherent: team and agent scopes saw the baseline while the
# member saw needs_approval on the same tool.
#
# Safe to ignore because an explicit choice is recorded elsewhere: the legacy
# toggle mirrors every write into a member MCPToolPolicy row
# (views._mirror_tool_approval_to_gateway), and scope rows outrank legacy ones.
# The gap is a pre-gateway member who explicitly picked needs_approval and was
# never mirrored. That only changes behaviour on teams whose admin has set a
# permissive preset — with no preset the resolve() fallback is needs_approval
# anyway — so the loosening is limited to teams that asked for it.
SYNC_DEFAULT_APPROVAL_STATE = "needs_approval"

# Exact verb forms that indicate a tool mutates or destroys state. Matched
# against the tool name only — descriptions are prose, where verbs like
# "archived" or "removes" show up in read-only tools. Deliberately the strong
# set only: an over-broad heuristic would make the "ask"/"block" presets gate
# nearly every tool.
_DESTRUCTIVE_TOKENS = frozenset(
    {
        "archive",
        "archived",
        "archives",
        "archiving",
        "ban",
        "banned",
        "banning",
        "bans",
        "cancel",
        "canceled",
        "canceling",
        "cancelled",
        "cancelling",
        "cancels",
        "delete",
        "deleted",
        "deletes",
        "deleting",
        "destroy",
        "destroyed",
        "destroying",
        "destroys",
        "drop",
        "dropped",
        "dropping",
        "drops",
        "erase",
        "erased",
        "erases",
        "erasing",
        "overwrite",
        "overwritten",
        "overwrites",
        "overwriting",
        "overwrote",
        "purge",
        "purged",
        "purges",
        "purging",
        "remove",
        "removed",
        "removes",
        "removing",
        "reset",
        "resets",
        "resetting",
        "revoke",
        "revoked",
        "revokes",
        "revoking",
        "suspend",
        "suspended",
        "suspending",
        "suspends",
        "terminate",
        "terminated",
        "terminates",
        "terminating",
        "truncate",
        "truncated",
        "truncates",
        "truncating",
        "wipe",
        "wiped",
        "wipes",
        "wiping",
    }
)

_CAMEL_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_WORD_SPLIT = re.compile(r"[^a-z0-9]+")


def _word_tokens(value: str) -> set[str]:
    normalized = _CAMEL_CASE_BOUNDARY.sub(" ", value).lower()
    return {token for token in _WORD_SPLIT.split(normalized) if token}


def is_destructive_tool(tool_name: str, annotations: dict[str, Any] | None = None) -> bool:
    """Heuristic used by presets and pattern-less org rules: destructive verb
    tokens in the tool name, or the server's own MCP ``destructiveHint``
    annotation. Annotations are untrusted upstream input, so a hint can only
    escalate — ``destructiveHint: false`` never clears a name match."""
    if annotations is not None and annotations.get("destructiveHint") is True:
        return True
    return bool(_word_tokens(tool_name) & _DESTRUCTIVE_TOKENS)


def member_preset_team_state(preset: str, tool_name: str, annotations: dict[str, Any] | None = None) -> str | None:
    """The default state a policy preset implies for a tool, or None when the
    preset is unset and imposes nothing."""
    if preset == "allow":
        return "approved"
    if preset == "user":
        return "needs_approval"
    if preset == "ask":
        return "needs_approval" if is_destructive_tool(tool_name, annotations) else "approved"
    if preset == "block":
        return "do_not_use" if is_destructive_tool(tool_name, annotations) else "approved"
    return None


@dataclass(frozen=True)
class GatewayCaller:
    kind: Literal["member", "agent"]
    user_id: int | None = None
    service_account_id: str | None = None


@dataclass(frozen=True)
class ResolvedPolicy:
    state: str
    # Which layer decided: "rule" | "scope" | "team" | "preset" | "legacy" | "default"
    decided_by: str
    # What the team-level chain (row or preset) would yield, ignoring the
    # caller's own scope. None when the team imposes nothing.
    team_state: str | None = None
    rule_name: str = ""
    rule_description: str = ""

    @property
    def locked(self) -> bool:
        """A rule match can't be loosened by any scope."""
        return self.decided_by == "rule"


@dataclass(frozen=True)
class _PolicyInputs:
    rules: tuple[MCPOrgRule, ...]
    policies: tuple[MCPToolPolicy, ...]
    preset: str


_STRICTNESS = {"do_not_use": 2, "needs_approval": 1, "approved": 0}


def is_policy_state_allowed(state: str, ceiling: str | None) -> bool:
    """Whether ``state`` is at least as restrictive as ``ceiling``."""
    if ceiling is None:
        return True
    return _STRICTNESS[state] >= _STRICTNESS[ceiling]


class PolicyContext:
    """Preloads every policy input for one (team, caller, server) so `resolve`
    is a pure in-memory lookup — callers resolve many tools in a loop."""

    def __init__(
        self,
        *,
        team_id: int,
        caller: GatewayCaller,
        gateway_server: MCPGatewayServer | None = None,
        gateway_server_id: UUID | None = None,
        installation: MCPServerInstallation | None = None,
        legacy_rows: dict[str, str] | None = None,
        _preloaded: _PolicyInputs | None = None,
    ) -> None:
        if gateway_server is not None:
            gateway_server_id = gateway_server.id
        if gateway_server_id is None:
            raise ValueError("PolicyContext requires a gateway server or gateway server ID")

        self.team_id = team_id
        self.caller = caller
        self.gateway_server = gateway_server
        self.gateway_server_id = gateway_server_id

        audience = "members" if caller.kind == "member" else "agents"
        # for_team: policy resolution also runs outside request scope (Max,
        # the agent proxy), where the fail-closed manager has no context.
        if _preloaded is None:
            canonical_team_id = resolve_effective_team_id(team_id)
            self._rules = tuple(
                MCPOrgRule.objects.for_team(canonical_team_id, canonical=True).filter(
                    enabled=True,
                    applies_to__in=("everyone", audience),
                )
            )
        else:
            canonical_team_id = team_id
            self._rules = _preloaded.rules

        policy_scope = Q(scope_type="team")
        if caller.kind == "member" and caller.user_id is not None:
            policy_scope |= Q(scope_type="member", scope_user_id=caller.user_id)
        elif caller.kind == "agent" and caller.service_account_id is not None:
            policy_scope |= Q(scope_type="agent", scope_service_account_id=caller.service_account_id)
        policies: Iterable[MCPToolPolicy] = (
            MCPToolPolicy.objects.for_team(canonical_team_id, canonical=True).filter(
                policy_scope, gateway_server_id=gateway_server_id
            )
            if _preloaded is None
            else _preloaded.policies
        )
        self._team_rows: dict[str, str] = {}
        self._scope_rows: dict[str, str] = {}
        for policy in policies:
            if policy.scope_type == "team":
                self._team_rows[policy.tool_name] = policy.state
            elif (
                policy.scope_type == "member"
                and caller.kind == "member"
                and caller.user_id is not None
                and policy.scope_user_id == caller.user_id
            ):
                self._scope_rows[policy.tool_name] = policy.state
            elif (
                policy.scope_type == "agent"
                and caller.kind == "agent"
                and caller.service_account_id is not None
                and str(policy.scope_service_account_id) == str(caller.service_account_id)
            ):
                self._scope_rows[policy.tool_name] = policy.state

        if _preloaded is not None:
            self.preset = _preloaded.preset
        else:
            config = TeamMCPGatewayConfig.objects.for_team(canonical_team_id, canonical=True).first()
            if config is None:
                self.preset = ""
            else:
                self.preset = config.member_default_preset if caller.kind == "member" else config.agent_default_preset

        raw_legacy = dict(legacy_rows or {}) if caller.kind == "member" else {}
        if legacy_rows is None and installation is not None and caller.kind == "member":
            for row in installation.tools.filter(removed_at__isnull=True).values("tool_name", "approval_state"):
                raw_legacy[row["tool_name"]] = row["approval_state"]
        self._legacy_rows = {
            tool_name: state for tool_name, state in raw_legacy.items() if state != SYNC_DEFAULT_APPROVAL_STATE
        }

    @classmethod
    def for_agent_servers(
        cls,
        *,
        team_id: int,
        service_account_id: str,
        gateway_servers: Iterable[MCPGatewayServer],
    ) -> dict[UUID, "PolicyContext"]:
        """Load policy inputs once for an agent's server catalog."""
        servers_by_id = {server.id: server for server in gateway_servers}
        if not servers_by_id:
            return {}

        canonical_team_id = resolve_effective_team_id(team_id)
        caller = GatewayCaller(kind="agent", service_account_id=service_account_id)
        rules = tuple(
            MCPOrgRule.objects.for_team(canonical_team_id, canonical=True).filter(
                enabled=True,
                applies_to__in=("everyone", "agents"),
            )
        )
        policies_by_server: dict[UUID, list[MCPToolPolicy]] = {}
        relevant_policies = (
            MCPToolPolicy.objects.for_team(canonical_team_id, canonical=True)
            .filter(gateway_server_id__in=servers_by_id)
            .filter(
                Q(scope_type="team")
                | Q(
                    scope_type="agent",
                    scope_service_account_id=service_account_id,
                )
            )
        )
        for policy in relevant_policies:
            policies_by_server.setdefault(policy.gateway_server_id, []).append(policy)

        config = TeamMCPGatewayConfig.objects.for_team(canonical_team_id, canonical=True).first()
        preset = config.agent_default_preset if config is not None else ""
        return {
            server_id: cls(
                team_id=team_id,
                caller=caller,
                gateway_server=server,
                _preloaded=_PolicyInputs(
                    rules=rules,
                    policies=tuple(policies_by_server.get(server_id, ())),
                    preset=preset,
                ),
            )
            for server_id, server in servers_by_id.items()
        }

    def _matching_rule(self, tool_name: str, annotations: dict[str, Any] | None) -> MCPOrgRule | None:
        matches = [
            rule
            for rule in self._rules
            if (
                fnmatch(tool_name, rule.tool_pattern)
                if rule.tool_pattern
                else is_destructive_tool(tool_name, annotations)
            )
        ]
        if not matches:
            return None
        return max(matches, key=lambda rule: _STRICTNESS.get(rule.effect, 0))

    def team_policy(self, tool_name: str, annotations: dict[str, Any] | None = None) -> tuple[str, str] | None:
        if tool_name in self._team_rows:
            return self._team_rows[tool_name], "team"
        preset_state = member_preset_team_state(self.preset, tool_name, annotations)
        return (preset_state, "preset") if preset_state is not None else None

    def team_state(self, tool_name: str, annotations: dict[str, Any] | None = None) -> str | None:
        team_policy = self.team_policy(tool_name, annotations)
        return team_policy[0] if team_policy is not None else None

    def resolve_team(self, tool_name: str, annotations: dict[str, Any] | None = None) -> ResolvedPolicy:
        """Resolve the editable team ceiling itself, rather than a caller under it."""
        team_policy = self.team_policy(tool_name, annotations)
        team_state = team_policy[0] if team_policy is not None else None

        rule = self._matching_rule(tool_name, annotations)
        if rule is not None:
            return ResolvedPolicy(
                state=rule.effect,
                decided_by="rule",
                team_state=team_state,
                rule_name=rule.name,
                rule_description=rule.description,
            )

        if team_policy is not None:
            state, decided_by = team_policy
            return ResolvedPolicy(state=state, decided_by=decided_by, team_state=state)

        return ResolvedPolicy(state="approved", decided_by="default", team_state=None)

    def resolve(self, tool_name: str, annotations: dict[str, Any] | None = None) -> ResolvedPolicy:
        team_policy = self.team_policy(tool_name, annotations)
        team_state = team_policy[0] if team_policy is not None else None

        rule = self._matching_rule(tool_name, annotations)
        if rule is not None:
            return ResolvedPolicy(
                state=rule.effect,
                decided_by="rule",
                team_state=team_state,
                rule_name=rule.name,
                rule_description=rule.description,
            )

        preference: tuple[str, str] | None = None
        if tool_name in self._scope_rows:
            preference = self._scope_rows[tool_name], "scope"
        elif tool_name in self._legacy_rows:
            preference = self._legacy_rows[tool_name], "legacy"

        if preference is not None:
            preference_state, preference_source = preference
            if team_policy is not None:
                ceiling_state, ceiling_source = team_policy
                if not is_policy_state_allowed(preference_state, ceiling_state):
                    return ResolvedPolicy(
                        state=ceiling_state,
                        decided_by=ceiling_source,
                        team_state=ceiling_state,
                    )
            return ResolvedPolicy(
                state=preference_state,
                decided_by=preference_source,
                team_state=team_state,
            )

        if team_policy is not None:
            ceiling_state, ceiling_source = team_policy
            return ResolvedPolicy(state=ceiling_state, decided_by=ceiling_source, team_state=ceiling_state)

        return ResolvedPolicy(state="needs_approval", decided_by="default", team_state=team_state)
