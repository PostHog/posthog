"""Gateway policy engine.

Resolves the effective state of one tool for one caller. Resolution order,
strictest source first:

1. Org rules — enabled team guardrails; a match locks the state.
2. The caller's scope row — the member's or agent's own `MCPToolPolicy`.
3. The team default row (`scope_type="team"`).
4. The team preset baseline (`member_default_preset` / `agent_default_preset`).
5. For members, the legacy per-installation approval state (pre-gateway rows
   that were never mirrored into policy rows).
6. `needs_approval` — freshly discovered tools are opt-in.

Every consumer (member proxy, agent proxy, Max, the gateway UI) resolves
through this module so their answers can't drift apart.
"""

import re
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Literal

from .models import MCPGatewayServer, MCPOrgRule, MCPServerInstallation, TeamMCPGatewayConfig

# Verbs that indicate a tool mutates or destroys state. Deliberately the
# strong set only — an over-broad heuristic would make the "ask"/"block"
# presets gate nearly every tool.
_DESTRUCTIVE_MARKERS = (
    "delete",
    "remove",
    "drop",
    "destroy",
    "purge",
    "wipe",
    "erase",
    "truncate",
    "terminate",
    "revoke",
    "reset",
    "overwrite",
    "cancel",
    "archive",
    "ban",
    "suspend",
)

_WORD_SPLIT = re.compile(r"[^a-z0-9]+")


def is_destructive_tool(tool_name: str, description: str = "") -> bool:
    """Heuristic used by presets and pattern-less org rules."""
    words = set(_WORD_SPLIT.split(tool_name.lower()))
    # camelCase names don't split on the regex; fall back to substring checks.
    lowered = tool_name.lower()
    if any(marker in words or marker in lowered for marker in _DESTRUCTIVE_MARKERS):
        return True
    description_words = set(_WORD_SPLIT.split(description.lower()))
    return any(marker in description_words for marker in _DESTRUCTIVE_MARKERS)


def member_preset_team_state(preset: str, tool_name: str, description: str = "") -> str | None:
    """The default state a policy preset implies for a tool, or None when the
    preset is unset and imposes nothing."""
    if preset == "allow":
        return "approved"
    if preset == "user":
        return "needs_approval"
    if preset == "ask":
        return "needs_approval" if is_destructive_tool(tool_name, description) else "approved"
    if preset == "block":
        return "do_not_use" if is_destructive_tool(tool_name, description) else "approved"
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


_STRICTNESS = {"do_not_use": 2, "needs_approval": 1, "approved": 0}


class PolicyContext:
    """Preloads every policy input for one (team, caller, server) so `resolve`
    is a pure in-memory lookup — callers resolve many tools in a loop."""

    def __init__(
        self,
        *,
        team_id: int,
        caller: GatewayCaller,
        gateway_server: MCPGatewayServer,
        installation: MCPServerInstallation | None = None,
    ) -> None:
        self.team_id = team_id
        self.caller = caller
        self.gateway_server = gateway_server

        audience = "members" if caller.kind == "member" else "agents"
        # for_team: policy resolution also runs outside request scope (Max,
        # the agent proxy), where the fail-closed manager has no context.
        self._rules = [
            rule
            for rule in MCPOrgRule.objects.for_team(team_id).filter(enabled=True)
            if rule.applies_to in ("everyone", audience)
        ]

        policies = gateway_server.tool_policies.all()
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

        config = TeamMCPGatewayConfig.objects.for_team(team_id).first()
        if config is None:
            self.preset = ""
        else:
            self.preset = config.member_default_preset if caller.kind == "member" else config.agent_default_preset

        self._legacy_rows: dict[str, str] = {}
        if installation is not None and caller.kind == "member":
            for row in installation.tools.filter(removed_at__isnull=True).values("tool_name", "approval_state"):
                self._legacy_rows[row["tool_name"]] = row["approval_state"]

    def _matching_rule(self, tool_name: str, description: str) -> MCPOrgRule | None:
        matches = [
            rule
            for rule in self._rules
            if (
                fnmatch(tool_name, rule.tool_pattern)
                if rule.tool_pattern
                else is_destructive_tool(tool_name, description)
            )
        ]
        if not matches:
            return None
        return max(matches, key=lambda rule: _STRICTNESS.get(rule.effect, 0))

    def team_state(self, tool_name: str, description: str = "") -> str | None:
        if tool_name in self._team_rows:
            return self._team_rows[tool_name]
        return member_preset_team_state(self.preset, tool_name, description)

    def resolve(self, tool_name: str, description: str = "") -> ResolvedPolicy:
        team_state = self.team_state(tool_name, description)

        rule = self._matching_rule(tool_name, description)
        if rule is not None:
            return ResolvedPolicy(
                state=rule.effect,
                decided_by="rule",
                team_state=team_state,
                rule_name=rule.name,
                rule_description=rule.description,
            )

        if tool_name in self._scope_rows:
            return ResolvedPolicy(state=self._scope_rows[tool_name], decided_by="scope", team_state=team_state)

        if tool_name in self._team_rows:
            return ResolvedPolicy(state=self._team_rows[tool_name], decided_by="team", team_state=team_state)

        preset_state = member_preset_team_state(self.preset, tool_name, description)
        if preset_state is not None:
            return ResolvedPolicy(state=preset_state, decided_by="preset", team_state=team_state)

        if tool_name in self._legacy_rows:
            return ResolvedPolicy(state=self._legacy_rows[tool_name], decided_by="legacy", team_state=team_state)

        return ResolvedPolicy(state="needs_approval", decided_by="default", team_state=team_state)
