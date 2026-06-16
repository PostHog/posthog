"""ORM-aware bridge between ``LLMSkill`` rows and the Django-free packaging core.

Everything that touches the database for export/marketplace lives here, so the
serialization and git synthesis stay unit-testable without booting the app.
"""

from django.core.cache import cache
from django.db.models import Max

from posthog.models import Team

from ..models.skills import LLMSkill, LLMSkillFile
from .git_smart_http import FileTree, SynthesizedRepo, synthesize_repo
from .packaging import SkillExport, SkillFileExport, build_marketplace_tree, compute_plugin_version

# One plugin per team (the agreed grouping). Stable, predictable names so skills are
# invocable as ``/posthog-skills:<name>`` once installed.
PLUGIN_NAME = "posthog-skills"
MARKETPLACE_NAME = "posthog-skills-marketplace"

_MARKETPLACE_AUTHOR = "PostHog"
_MARKETPLACE_COMMIT_MESSAGE = "PostHog skills marketplace"
# The cache key already embeds the content-derived plugin version, so a hit is only ever
# the current content. The TTL just bounds memory for superseded versions.
_MARKETPLACE_REPO_CACHE_TTL_SECONDS = 300


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


def synthesize_team_marketplace_repo(team: Team) -> SynthesizedRepo:
    """Return the synthesized git repo for a team's marketplace, cached on the content version.

    A normal ``git clone`` hits ``info/refs`` then ``git-upload-pack``, and auto-update polls
    repeatedly — synthesizing the whole repo (loading every skill + file, hashing every blob)
    each time would be wasteful. The cache key embeds ``_team_plugin_version`` (which changes
    exactly when content changes), so a hit is always current and any change invalidates it.
    """
    version = _team_plugin_version(team)
    cache_key = f"skills_marketplace_repo:{team.id}:{version}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    tree = build_team_marketplace_tree(team, version=version)
    repo = synthesize_repo(tree, author=_MARKETPLACE_AUTHOR, message=_MARKETPLACE_COMMIT_MESSAGE)
    cache.set(cache_key, repo, timeout=_MARKETPLACE_REPO_CACHE_TTL_SECONDS)
    return repo


def build_team_marketplace_tree(team: Team, version: str | None = None) -> FileTree:
    """Synthesize the full plugin-marketplace file tree for a team's latest skills."""
    if version is None:
        version = _team_plugin_version(team)

    # Lean query: the marketplace only needs the latest live skills, not the version-history
    # annotations / created_by join that get_latest_skills_queryset adds.
    skills = list(LLMSkill.objects.filter(team=team, deleted=False, is_latest=True).order_by("name"))

    files_by_skill = _files_by_skill_id(skills)
    exports = [skill_to_export(skill, files_by_skill.get(skill.id, [])) for skill in skills]

    return build_marketplace_tree(
        plugin_name=PLUGIN_NAME,
        plugin_description=f"Shared agent skills for {team.name}",
        plugin_version=version,
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
    # when the most-recently-updated skill is archived. Milliseconds (not seconds) so two edits
    # within the same second still produce distinct versions and clients don't miss an update.
    latest = LLMSkill.objects.filter(team=team).aggregate(latest=Max("updated_at"))["latest"]
    return compute_plugin_version(int(latest.timestamp() * 1000)) if latest is not None else "1.0.0"
