from __future__ import annotations

from dataclasses import dataclass

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
    # "canonical" | "custom" — who owns the skill row (see `lazy_seed.scout_skill_origin`). The
    # prompt builder gates the self-improvement section on it: a custom scout is invited to record
    # `improve:` suggestions for its own body (the team owns that body and can apply them); a
    # canonical scout is not, so the prompt never nudges a team into diverging a seeded row.
    origin: str


def is_signals_scout_skill(skill: LLMSkill) -> bool:
    return skill.name.startswith(SIGNALS_SCOUT_SKILL_PREFIX)


def load_skill_for_run(team: Team, skill_name: str, *, version: int | None = None) -> LoadedSkill:
    """Resolve a skill on the team's namespace and load its body + file manifest.

    Pass `version=None` to follow-latest. The `signals-scout-*` prefix is not enforced
    here — the management command can hand-trigger any skill on the team.
    """
    # Lazy imports, both to break cycles: `lazy_seed` imports this module at top level
    # (SIGNALS_SCOUT_SKILL_PREFIX), and `products.skills.backend.api` triggers a temporal module
    # load that this package is itself imported from at temporal-worker boot. Models only is fine.
    from products.signals.backend.scout_harness.lazy_seed import scout_skill_origin
    from products.skills.backend.api.skill_services import get_skill_by_name_from_db

    skill = get_skill_by_name_from_db(team, skill_name, version=version)
    if skill is None:
        raise SkillNotFoundError(
            f"No skill named '{skill_name}' found on team {team.id}"
            + (f" (version {version})" if version is not None else "")
        )
    file_rows = LLMSkillFile.objects.filter(skill=skill).only("path", "content_type").order_by("path")
    return LoadedSkill(
        name=skill.name,
        version=skill.version,
        body=skill.body,
        description=skill.description,
        allowed_tools=list(skill.allowed_tools or []),
        files=[LoadedSkillFile(path=f.path, content_type=f.content_type) for f in file_rows],
        skill_id=str(skill.id),
        origin=scout_skill_origin(skill.name, skill.metadata),
    )
