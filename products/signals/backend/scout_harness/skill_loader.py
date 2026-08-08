from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from django.db.models import Max, Min

from posthog.models.team.team import Team

from products.skills.backend.models.skills import LLMSkill, LLMSkillFile, LLMSkillOwner

# Naming contract for skills that steer a Signals-agent run.
SIGNALS_SCOUT_SKILL_PREFIX = "signals-scout-"

# Tools whose presence in a skill's `allowed_tools` opts the scout into the report-authoring channel
# (it writes full `SignalReport`s via `emit_report` / `edit_report` instead of firing weak signals).
# This single set is read in three places that must agree: the runner picks the MCP scope posture from
# it (`runner.py`), the prompt builder steers a report scout differently because of it (`prompt.py`),
# and the viewset fail-closes the write on it (`views.py`). Keep them resolving the same set.
REPORT_CHANNEL_TOOLS: frozenset[str] = frozenset({"emit_report", "edit_report"})

# Per-skill opt-in user-facing WRITE scopes.
# A skill lists one of these tool names in `allowed_tools` to request the mapped scope.
# This mirrors the report-channel opt-in, but grants ordinary product writes.
# Scopes already in the fleet-wide `SCOUT_USER_WRITE_SCOPES` need no opt-in.
# The runner adds the mapped scope to the sandbox token of the scout that asked.
# Opt-ins only apply to a pristine canonical skill (`origin == "canonical"`): a seeded row
# whose content hash still matches the repo copy. A custom or in-place-diverged skill can list
# the same tool in `allowed_tools`, but the opt-in resolver hands back nothing for it. This is
# the security gate: any project member with `llm_skill:write` can edit a skill's body and
# `allowed_tools` through the generic skills API, so a member-editable declaration must never
# mint a user-write scope. The canonical skill bodies are reviewed in the repo (including the
# write's narrow purpose), and the sandbox token runs as the team's acting user, a confused
# deputy if the steering body is member-controlled.
#
# The MCP server filters its tool catalog by token scope, so a scout without `insight:write`
# never sees `insight-update`. The PostHog API re-checks the scope on the call.
# Add an entry only when a scout genuinely needs that write unattended. The value must belong to
# `MCP_WRITE_SCOPES`, or token resolution raises.
OPT_IN_USER_WRITE_TOOLS: dict[str, str] = {
    # Lets a scout fix a saved insight's name or description in place (the insight-hygiene scout).
    # Grants the full `insight:write` object: create, update, and delete all surface.
    # The skill body must restrict itself to metadata-only edits.
    "update_insights": "insight:write",
}


def skill_opted_in_user_write_scopes(allowed_tools: list[str] | None, origin: str = "canonical") -> list[str]:
    """The user-facing write scopes a skill requested in `allowed_tools`, in stable order.

    Returns an empty list unless `origin` is `"canonical"`. A custom skill, or a canonical row
    the team edited in place (both classify as custom), gets no user-write scope even when its
    `allowed_tools` lists an opt-in tool. The MCP tool catalog then simply lacks the tool: the
    run degrades to read-only + reports instead of holding a member-authored write privilege.

    Validate each mapped scope against `MCP_WRITE_SCOPES` (imported lazily to keep the import
    graph small). A bad entry in the repo-controlled map raises here, close to the runner,
    instead of minting a token that carries a scope nothing understands.
    """
    from posthog.temporal.oauth import MCP_WRITE_SCOPES

    if origin != "canonical":
        return []
    tools = set(allowed_tools or [])
    resolved = []
    for tool, scope in OPT_IN_USER_WRITE_TOOLS.items():
        if tool not in tools:
            continue
        if scope not in MCP_WRITE_SCOPES:
            raise ValueError(
                f"OPT_IN_USER_WRITE_TOOLS maps {tool!r} to {scope!r}, which is not an advertised MCP write scope"
            )
        resolved.append(scope)
    return resolved


def skill_uses_report_channel(allowed_tools: list[str] | None) -> bool:
    """Whether a skill opted into the report-authoring channel via its `allowed_tools`."""
    return bool(REPORT_CHANNEL_TOOLS & set(allowed_tools or []))


def resolve_report_channel_variant(allowed_tools: list[str] | None) -> str:
    """Which report tools a run held: `none`, `emit`, `edit`, or `both`.

    Finer-grained than `skill_uses_report_channel` because the prompt builder branches on the two
    capabilities separately (the follow-up re-surface clause, the self-improvement escalation path,
    and the channel sections all differ between emit-only and edit-only), so a single boolean would
    pool runs that were given materially different instructions. Stamped on the run row, where
    `allowed_tools` being editable means the variant cannot be recovered afterwards.
    """
    tools = set(allowed_tools or [])
    can_emit = "emit_report" in tools
    can_edit = "edit_report" in tools
    if can_emit and can_edit:
        return "both"
    if can_emit:
        return "emit"
    if can_edit:
        return "edit"
    return "none"


class SkillNotFoundError(LookupError):
    """The team has no skill matching the requested name."""


@dataclass(frozen=True)
class LoadedSkillFile:
    path: str
    content_type: str


# Editors surfaced in the prompt beyond the creator. Distinct authors per skill are few in
# practice; the cap only guards the prompt against a pathologically churned skill.
MAX_SKILL_EDITORS_IN_PROMPT = 5


@dataclass(frozen=True)
class SkillAuthor:
    """One human tied to the skill for reviewer routing.

    `role="owner"` is the explicit, durable owner set (from `LLMSkillOwner`) and takes precedence.
    `creator`/`editor` are the legacy reconstruction from version-row authorship, used only when a
    skill has no explicit owners. For an owner, `last_authored_at` is the owner-since date.
    """

    name: str
    email: str
    role: Literal["owner", "creator", "editor"]
    last_authored_at: datetime


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    # Snapshotted onto the run row so a historical run can be reproduced even after re-versioning.
    version: int
    body: str
    description: str
    # Portable skill metadata, and the opt-in gate for the report channel. The harness reads it at
    # spawn time: listing `emit_report` / `edit_report` here makes the runner grant the
    # `signals_scout_reports` scope posture (vs plain `signals_scout`), which carries
    # `signal_scout_report:write` — the scope the report tools require. A scout that doesn't list them
    # gets no report scope, so the MCP server strips those tools from its toolset (exposure is
    # scope-level at the OAuth/MCP boundary). The `emit-report` / `edit-report` viewset actions also
    # re-check this list server-side (`views.SignalScoutRunViewSet._assert_report_tool_opted_in`) as a
    # fail-closed gate on the write. Downstream consumers (e.g. Claude Code) may also read it.
    allowed_tools: list[str]
    files: list[LoadedSkillFile]
    skill_id: str
    # "canonical" | "custom" — who owns the skill row (see `lazy_seed.scout_skill_row_origin`;
    # a seeded row the team has edited in place classifies as custom). The prompt builder gates
    # the self-improvement section on it: a custom scout is invited to record `improve:`
    # suggestions for its own body (the team owns that body and can apply them); a pristine
    # canonical scout is not, so the prompt never nudges a team into diverging a seeded row.
    origin: Literal["canonical", "custom"]
    # The humans who own the skill body, resolved from its version rows: creator first (the
    # earliest version with a known author — a seeded row's v1 is system-authored with no
    # `created_by`, so a diverged canonical's creator is whoever first edited it), then editors
    # ordered most-recent-edit first. Custom scouts only (empty for canonical) — the prompt
    # renders it into the run identity so the scout can route self-improvement reports to the
    # skill's owners instead of guessing. Version rows can't reveal authorship any other way:
    # each row's `created_by` is whoever published *that* version, so the pinned (latest)
    # version alone would misattribute the skill to its last editor.
    authors: list[SkillAuthor]


def is_signals_scout_skill(skill: LLMSkill) -> bool:
    return skill.name.startswith(SIGNALS_SCOUT_SKILL_PREFIX)


def resolve_skill_owner_user_uuids(team: Team, skill_name: str) -> list[str]:
    """Owner user UUIDs for a logical skill, seed-creator first — for the reviewer guardrail.

    Restricted to `team.all_users_with_access()` (same privacy boundary as the author scan): an
    owner who lost access can't be routed a review and their identity shouldn't leak downstream.
    """
    return [
        str(uuid)
        # canonical=True → exact environment team, matching how LLMSkill is scoped (see LLMSkillOwner).
        for uuid in LLMSkillOwner.objects.for_team(team.id, canonical=True)
        .filter(skill_name=skill_name, user__in=team.all_users_with_access())
        .order_by("created_at", "id")
        .values_list("user__uuid", flat=True)
    ]


def _skill_has_owner_rows(team: Team, skill_name: str) -> bool:
    """Whether the logical skill has any owner rows at all — including owners who lost access.

    Distinguishes "no explicit owners, use version history" from "owned, but currently unroutable",
    so the latter never silently drifts back to the version-history heuristic.
    """
    return LLMSkillOwner.objects.for_team(team.id, canonical=True).filter(skill_name=skill_name).exists()


def _resolve_owner_authors(team: Team, skill_name: str) -> list[SkillAuthor]:
    """The explicit owner set as `SkillAuthor`s (role="owner"), seed-creator first.

    Same membership filter as the legacy scan. Empty when the skill has no explicit owners, which
    is the signal to fall back to version-history reconstruction.
    """
    rows = (
        # canonical=True → exact environment team, matching how LLMSkill is scoped (see LLMSkillOwner).
        LLMSkillOwner.objects.for_team(team.id, canonical=True)
        .filter(skill_name=skill_name, user__in=team.all_users_with_access())
        .values("user__first_name", "user__last_name", "user__email", "created_at")
        .order_by("created_at", "id")
    )
    authors: list[SkillAuthor] = []
    for row in rows:
        # Collapse whitespace so a multi-line display name can't break the prompt's one-line list item.
        name = " ".join(f"{row['user__first_name']} {row['user__last_name']}".split())
        authors.append(
            SkillAuthor(
                name=name or row["user__email"],
                email=row["user__email"],
                role="owner",
                last_authored_at=row["created_at"],
            )
        )
    return authors


def resolve_skill_authors(team: Team, skill_name: str) -> list[SkillAuthor]:
    """Humans to route reviews to. Prefers the explicit owner set; falls back to version history.

    When the skill carries explicit owners (`LLMSkillOwner`), they win — ownership is keyed on the
    logical skill and never drifts when the body is edited, so it's the authoritative answer to
    "who owns this scout?". Only when there are no owners does this reconstruct authorship from
    version rows (creator first, then editors by recency), the best-effort legacy heuristic that a
    bulk edit could misattribute.

    Version-history path: one indexed aggregate over all version rows for `(team, name)` — capped at
    `MAX_SKILL_VERSION`, so cheap regardless of churn. Rows with a null `created_by` (system-seeded
    versions, deleted users) carry no routable identity and are skipped.

    Both paths restrict to `team.all_users_with_access()` — the same boundary the
    `scout-members-list` reviewer roster uses. A former member's profile (notably the
    self-editable display name) must not keep flowing into a privileged prompt after their
    access is revoked, and an unroutable author would only waste a slot anyway.
    """
    owners = _resolve_owner_authors(team, skill_name)
    if owners:
        return owners
    # A skill with owner rows is authoritatively owned — even if every owner has since lost access.
    # Falling back to version-history reconstruction here would re-introduce exactly the editor drift
    # this primitive exists to prevent, so an owned-but-currently-unroutable skill gets no reviewer
    # rather than a guessed one. Only a skill with *no* owner rows uses the legacy heuristic.
    if _skill_has_owner_rows(team, skill_name):
        return []

    rows = (
        LLMSkill.objects.filter(
            team=team,
            name=skill_name,
            deleted=False,
            created_by__isnull=False,
            created_by__in=team.all_users_with_access(),
        )
        .values("created_by__uuid", "created_by__first_name", "created_by__last_name", "created_by__email")
        .annotate(first_authored_at=Min("created_at"), last_authored_at=Max("created_at"))
        .order_by("first_authored_at")
    )
    people = list(rows)
    if not people:
        return []

    def to_author(person: dict, role: Literal["creator", "editor"]) -> SkillAuthor:
        # Collapse whitespace so a multi-line display name can't break out of the prompt's
        # one-line list-item structure.
        name = " ".join(f"{person['created_by__first_name']} {person['created_by__last_name']}".split())
        return SkillAuthor(
            name=name or person["created_by__email"],
            email=person["created_by__email"],
            role=role,
            last_authored_at=person["last_authored_at"],
        )

    creator, *editors = people
    editors.sort(key=lambda p: p["last_authored_at"], reverse=True)
    return [to_author(creator, "creator")] + [to_author(p, "editor") for p in editors[:MAX_SKILL_EDITORS_IN_PROMPT]]


def load_skill_for_run(
    team: Team, skill_name: str, *, version: int | None = None, include_authors: bool = False
) -> LoadedSkill:
    """Resolve a skill on the team's namespace and load its body + file manifest.

    Pass `version=None` to follow-latest. The `signals-scout-*` prefix is not enforced
    here — the management command can hand-trigger any skill on the team.

    `include_authors` is for the prompt-building path only (the runner). Other callers —
    notably the report-authorization gate in `views._assert_report_tool_opted_in`, which loads
    the skill on every report write just to check `allowed_tools` — must not pay for the
    membership + version-history author scan, so it defaults off.
    """
    # Lazy imports, both to break cycles: `lazy_seed` imports this module at top level
    # (SIGNALS_SCOUT_SKILL_PREFIX), and `products.skills.backend.api` triggers a temporal module
    # load that this package is itself imported from at temporal-worker boot. Models only is fine.
    from products.signals.backend.scout_harness.lazy_seed import scout_skill_row_origin
    from products.skills.backend.api.skill_services import get_skill_by_name_from_db

    skill = get_skill_by_name_from_db(team, skill_name, version=version)
    if skill is None:
        raise SkillNotFoundError(
            f"No skill named '{skill_name}' found on team {team.id}"
            + (f" (version {version})" if version is not None else "")
        )
    file_rows = LLMSkillFile.objects.filter(skill=skill).only("path", "content_type").order_by("path")
    origin = scout_skill_row_origin(skill)
    return LoadedSkill(
        name=skill.name,
        version=skill.version,
        body=skill.body,
        description=skill.description,
        allowed_tools=list(skill.allowed_tools or []),
        files=[LoadedSkillFile(path=f.path, content_type=f.content_type) for f in file_rows],
        skill_id=str(skill.id),
        origin=origin,
        # Only a custom scout's prompt renders authorship (canonical bodies are PostHog-owned),
        # so skip the extra queries unless the caller builds a prompt and the row is custom.
        authors=resolve_skill_authors(team, skill_name) if include_authors and origin == "custom" else [],
    )
