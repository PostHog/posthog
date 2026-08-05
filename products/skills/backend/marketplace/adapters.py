"""ORM-aware bridge between ``LLMSkill`` rows and the Django-free packaging core.

Everything that touches the database for export/marketplace lives here, so the
serialization and git synthesis stay unit-testable without booting the app.
"""

from typing import Any

from django.core.cache import cache
from django.db.models import Max

import structlog
from rest_framework import serializers

from posthog.models import Team

from ..api.skill_serializers import validate_skill_file_path
from ..models.skills import LLMSkill, LLMSkillFile
from .git_smart_http import FileTree, SynthesizedRepo, synthesize_repo
from .packaging import SkillExport, SkillFileExport, build_marketplace_tree, compute_plugin_version

logger = structlog.get_logger(__name__)

# One plugin per team (the agreed grouping). Stable, predictable names so skills are
# invocable as ``/posthog-skill-store:<name>`` once installed.
PLUGIN_NAME = "posthog-skill-store"
MARKETPLACE_NAME = "posthog-skill-store-marketplace"

_MARKETPLACE_AUTHOR = "PostHog"
_MARKETPLACE_COMMIT_MESSAGE = "PostHog skills marketplace"
# The cache key already embeds the content-derived plugin version, so a hit is only ever
# the current content. The TTL just bounds memory for superseded versions.
_MARKETPLACE_REPO_CACHE_TTL_SECONDS = 300
# The plugin version is Max(updated_at) over a team's skill rows — cheap, but it runs on every
# info/refs, every upload-pack, and every auto-update poll. Briefly cache it so a clone + a burst of
# polls collapse to one query per window instead of one per request. Auto-update detection lags by
# at most this TTL (content is never stale — only the version label that triggers a re-pull).
_MARKETPLACE_VERSION_CACHE_TTL_SECONDS = 15

# Bound the in-memory/cached footprint of a team's marketplace so an outlier team with very many
# (or very large) skills can't OOM the web worker on clone. Past this cumulative content size we
# skip the remaining skills (logged) rather than synthesize an unbounded tree.
_MAX_MARKETPLACE_TREE_BYTES = 64_000_000
# Don't pickle a very large synthesized repo into the shared cache — serve it uncached instead.
_MAX_CACHEABLE_PACKFILE_BYTES = 16_000_000


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
    version = _team_plugin_version_cached(team)
    cache_key = f"skills_marketplace_repo:{team.id}:{version}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    tree = build_team_marketplace_tree(team, version=version)
    repo = synthesize_repo(tree, author=_MARKETPLACE_AUTHOR, message=_MARKETPLACE_COMMIT_MESSAGE)
    if len(repo.packfile) <= _MAX_CACHEABLE_PACKFILE_BYTES:
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

    # Drop any skill whose bundled-file paths would synthesize a corrupt/uncloneable git tree
    # (e.g. legacy rows that predate the stricter path validation, or case-only collisions). One
    # bad skill is skipped rather than 500-ing the whole team's marketplace clone. We also cap the
    # cumulative content size: past the ceiling, remaining skills are skipped so a pathological team
    # can't OOM the clone.
    exports: list[SkillExport] = []
    skipped_unsafe: list[str] = []
    skipped_oversize: list[str] = []
    total_bytes = 0
    for skill in skills:
        files = files_by_skill.get(skill.id, [])
        if not _skill_files_are_tree_safe(files):
            skipped_unsafe.append(skill.name)
            continue
        skill_bytes = len((skill.body or "").encode("utf-8")) + sum(
            len((f.content or "").encode("utf-8")) for f in files
        )
        # Always include at least one skill (per-skill content is already bounded); skip the rest
        # once we'd cross the team ceiling.
        if exports and total_bytes + skill_bytes > _MAX_MARKETPLACE_TREE_BYTES:
            skipped_oversize.append(skill.name)
            continue
        total_bytes += skill_bytes
        exports.append(skill_to_export(skill, files))
    if skipped_unsafe:
        logger.warning("skills_marketplace_skipped_unsafe_skills", team_id=team.id, skills=skipped_unsafe)
    if skipped_oversize:
        logger.warning(
            "skills_marketplace_skipped_oversize",
            team_id=team.id,
            skipped_count=len(skipped_oversize),
            included_bytes=total_bytes,
        )

    return build_marketplace_tree(
        plugin_name=PLUGIN_NAME,
        plugin_description=f"Shared agent skills for {team.name}",
        plugin_version=version,
        owner_name=team.organization.name,
        marketplace_name=MARKETPLACE_NAME,
        skills=exports,
    )


def _skill_files_are_tree_safe(files: list[LLMSkillFile]) -> bool:
    """True if every file path is valid and no two collide case-insensitively — i.e. the set
    synthesizes a tree real git can clone on any filesystem."""
    seen_lower: set[str] = set()
    for skill_file in files:
        try:
            validate_skill_file_path(skill_file.path)
        except serializers.ValidationError:
            return False
        lowered = skill_file.path.lower()
        if lowered in seen_lower:
            return False
        seen_lower.add(lowered)
    return True


def _files_by_skill_id(skills: list[LLMSkill]) -> dict[Any, list[LLMSkillFile]]:
    grouped: dict[Any, list[LLMSkillFile]] = {}  # keyed by skill UUID (matches skill.id lookups)
    if not skills:
        return grouped
    for skill_file in LLMSkillFile.objects.filter(skill__in=skills).order_by("path"):
        grouped.setdefault(skill_file.skill_id, []).append(skill_file)
    return grouped


def _team_plugin_version_cached(team: Team) -> str:
    """``_team_plugin_version`` behind a short TTL so the Max() query runs ~once per window per team
    instead of on every clone / upload-pack / auto-update poll."""
    cache_key = f"skills_marketplace_version:{team.id}"
    version = cache.get(cache_key)
    if version is None:
        version = _team_plugin_version(team)
        cache.set(cache_key, version, timeout=_MARKETPLACE_VERSION_CACHE_TTL_SECONDS)
    return version


def _team_plugin_version(team: Team) -> str:
    # Max over ALL of the team's skill rows, including archived ones. Publishes add a row with a
    # fresh updated_at and archive_skill bumps updated_at on the rows it soft-deletes, so this is
    # monotonic and reflects archives. Deriving it from only live skills would regress the version
    # when the most-recently-updated skill is archived. Milliseconds (not seconds) so two edits
    # within the same second still produce distinct versions and clients don't miss an update.
    latest = LLMSkill.objects.filter(team=team).aggregate(latest=Max("updated_at"))["latest"]
    return compute_plugin_version(int(latest.timestamp() * 1000)) if latest is not None else "1.0.0"
