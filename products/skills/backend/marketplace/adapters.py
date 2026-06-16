"""ORM-aware bridge between ``LLMSkill`` rows and the Django-free packaging core.

Everything that touches the database for export/marketplace lives here, so the
serialization and git synthesis stay unit-testable without booting the app.
"""

from django.db.models import Max

from posthog.models import Team

from ..api.skill_services import get_latest_skills_queryset
from ..models.skills import LLMSkill, LLMSkillFile
from .git_smart_http import FileTree
from .packaging import SkillExport, SkillFileExport, build_marketplace_tree, compute_plugin_version

# One plugin per team (the agreed grouping). Stable, predictable names so skills are
# invocable as ``/posthog-skills:<name>`` once installed.
PLUGIN_NAME = "posthog-skills"
MARKETPLACE_NAME = "posthog-skills-marketplace"


def skill_to_export(skill: LLMSkill, files: list[LLMSkillFile]) -> SkillExport:
    return SkillExport(
        name=skill.name,
        description=skill.description,
        body=skill.body,
        version=skill.version,
        license=skill.license or "",
        compatibility=skill.compatibility or "",
        allowed_tools=list(skill.allowed_tools or []),
        metadata=dict(skill.metadata or {}),
        files=[SkillFileExport(path=f.path, content=f.content, content_type=f.content_type) for f in files],
    )


def load_skill_export(skill: LLMSkill) -> SkillExport:
    files = list(LLMSkillFile.objects.filter(skill=skill).order_by("path"))
    return skill_to_export(skill, files)


def build_team_marketplace_tree(team: Team) -> FileTree:
    """Synthesize the full plugin-marketplace file tree for a team's latest skills."""
    skills = list(get_latest_skills_queryset(team).order_by("name"))

    files_by_skill = _files_by_skill_id(skills)
    exports = [skill_to_export(skill, files_by_skill.get(skill.id, [])) for skill in skills]

    return build_marketplace_tree(
        plugin_name=PLUGIN_NAME,
        plugin_description=f"Shared agent skills for {team.name}",
        plugin_version=_team_plugin_version(team),
        owner_name=team.organization.name,
        marketplace_name=MARKETPLACE_NAME,
        skills=exports,
    )


def _files_by_skill_id(skills: list[LLMSkill]) -> dict[str, list[LLMSkillFile]]:
    grouped: dict[str, list[LLMSkillFile]] = {}
    if not skills:
        return grouped
    for skill_file in LLMSkillFile.objects.filter(skill__in=skills).order_by("path"):
        grouped.setdefault(skill_file.skill_id, []).append(skill_file)
    return grouped


def _team_plugin_version(team: Team) -> str:
    # Max over ALL of the team's skill rows, including archived ones. Publishes add a row with a
    # fresh updated_at and archive_skill bumps updated_at on the rows it soft-deletes, so this is
    # monotonic and reflects archives. Deriving it from only live skills would regress the version
    # when the most-recently-updated skill is archived.
    latest = LLMSkill.objects.filter(team=team).aggregate(latest=Max("updated_at"))["latest"]
    return compute_plugin_version(int(latest.timestamp())) if latest is not None else "1.0.0"
