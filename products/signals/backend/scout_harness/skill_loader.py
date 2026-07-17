from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from django.db.models import Max, Min

from posthog.models.team.team import Team

from products.skills.backend.models.skills import LLMSkill, LLMSkillFile

# Naming contract for skills that steer a Signals-agent run.
SIGNALS_SCOUT_SKILL_PREFIX = "signals-scout-"

# Tools whose presence in a skill's `allowed_tools` opts the scout into the report-authoring channel
# (it writes full `SignalReport`s via `emit_report` / `edit_report` instead of firing weak signals).
# This single set is read in three places that must agree: the runner picks the MCP scope posture from
# it (`runner.py`), the prompt builder steers a report scout differently because of it (`prompt.py`),
# and the viewset fail-closes the write on it (`views.py`). Keep them resolving the same set.
REPORT_CHANNEL_TOOLS: frozenset[str] = frozenset({"emit_report", "edit_report"})


def skill_uses_report_channel(allowed_tools: list[str] | None) -> bool:
    """Whether a skill opted into the report-authoring channel via its `allowed_tools`."""
    return bool(REPORT_CHANNEL_TOOLS & set(allowed_tools or []))


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
    """One human who published at least one version of the skill, for reviewer routing."""

    name: str
    email: str
    role: Literal["creator", "editor"]
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


def resolve_skill_authors(team: Team, skill_name: str) -> list[SkillAuthor]:
    """Distinct humans across the skill's version rows: creator first, then editors by recency.

    One indexed aggregate over all version rows for `(team, name)` — versions are capped at
    `MAX_SKILL_VERSION`, so this stays cheap regardless of edit churn. Rows with a null
    `created_by` (system-seeded versions, deleted users) carry no routable identity and are
    skipped; a skill with only such rows resolves to no authors.

    Authors are restricted to `team.all_users_with_access()` — the same boundary the
    `scout-members-list` reviewer roster uses. A former member's profile (notably the
    self-editable display name) must not keep flowing into a privileged prompt after their
    access is revoked, and an unroutable author would only waste an editor slot anyway.
    """
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
