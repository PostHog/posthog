"""ORM-aware bridge between ``LLMSkill`` rows and the Django-free packaging core.

Everything that touches the database for export/marketplace lives here, so the
serialization and git synthesis stay unit-testable without booting the app.
"""

from typing import Any, Literal

from django.core.cache import cache
from django.db.models import F, Func, IntegerField, Max, Q, QuerySet, Sum
from django.db.models.functions import Coalesce

import structlog
from rest_framework import serializers

from posthog.dataclasses import frozen
from posthog.models import Team, User

from ..api.skill_serializers import validate_skill_file_path
from ..api.skill_services import SKILL_NAME_PATTERN, skill_names_owned_by
from ..models.skills import LLMSkill, LLMSkillFile
from .git_smart_http import FileTree, SynthesizedRepo, synthesize_repo
from .packaging import (
    SPEC_DESCRIPTION_MAX_LENGTH,
    SkillExport,
    SkillFileExport,
    SkillStub,
    build_marketplace_tree,
    build_skill_stub_tree,
    build_skill_tree,
    build_skills_bundle_zip,
    compute_plugin_version,
    file_tree_bytes,
    validate_for_export,
)

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

# A sandbox bundle is fetched once per run and unpacked into the harness's skill directories, so it
# is bounded by what a coding agent can usefully load, not by what the team owns.
MAX_BUNDLE_SKILLS = 20
MAX_BUNDLE_BYTES = 5_000_000


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


@frozen
class SkillBundle:
    zip_bytes: bytes
    included: list[str]
    dropped: list[str]
    skipped: list[str]


BundleContent = Literal["stub", "full"]


class _OctetLength(Func):
    function = "OCTET_LENGTH"
    output_field = IntegerField()


def _bundle_candidates(team: Team, user: User, readable_skills: QuerySet[LLMSkill]) -> QuerySet[LLMSkill]:
    # Creation seeds an owner row, but skills that predate owners only carry ``created_by``. The
    # version 1 row keeps the original creator; later versions are stamped with whoever edited them.
    created_names = LLMSkill.objects.filter(team=team, deleted=False, version=1, created_by=user).values("name")
    return (
        readable_skills.filter(team=team, deleted=False, is_latest=True)
        .exclude(category="scout")
        .filter(Q(name__in=created_names) | Q(name__in=skill_names_owned_by(team, user.id)))
        .order_by("-updated_at", "name")
    )


def build_skill_bundle(
    team: Team, user: User, readable_skills: QuerySet[LLMSkill], content: BundleContent = "stub"
) -> SkillBundle:
    """One zip of the skills a user created or owns, for unpacking into a skills directory.

    ``content="stub"`` writes one ``SKILL.md`` per skill with only its name and description and a
    body that tells the agent to fetch the real skill over MCP when it is invoked. That keeps the
    per-run payload to discovery metadata; skill content only moves when a skill is used.
    ``content="full"`` writes the whole skill: rendered ``SKILL.md``, bundled files and the Codex
    sidecar.

    ``readable_skills`` is the caller's access-filtered view of the team's skills. The walk only
    selects from it, so a skill the list endpoint would hide from the user stays out of the bundle.

    Newest first. The walk stops at the first skill that would cross the count or byte cap; every
    skill after it is ``dropped`` and only its name is read. Skills that fail the spec check or
    carry a name or path the harness could not unpack safely are ``skipped`` and do not count.
    Scouts are excluded because the scout harness loads its own skill.
    """
    candidates = _bundle_candidates(team, user, readable_skills)
    trees, dropped, skipped = _walk_stubs(candidates) if content == "stub" else _walk_full(candidates)

    if skipped:
        logger.warning("skills_bundle_skipped", team_id=team.id, user_id=user.id, skills=skipped)
    if dropped:
        logger.warning("skills_bundle_dropped_over_cap", team_id=team.id, user_id=user.id, skills=dropped)

    return SkillBundle(
        zip_bytes=build_skills_bundle_zip(trees),
        included=list(trees),
        dropped=dropped,
        skipped=skipped,
    )


def _walk_stubs(candidates: QuerySet[LLMSkill]) -> tuple[dict[str, FileTree], list[str], list[str]]:
    trees: dict[str, FileTree] = {}
    dropped: list[str] = []
    skipped: list[str] = []
    for row in candidates.values("name", "description", "version"):
        name = row["name"]
        if len(trees) >= MAX_BUNDLE_SKILLS:
            dropped.append(name)
            continue
        stub = SkillStub(name=name, description=row["description"], version=row["version"])
        if not SKILL_NAME_PATTERN.match(name) or not _stub_is_spec_valid(stub):
            skipped.append(name)
            continue
        trees[name] = build_skill_stub_tree(stub)
    return trees, dropped, skipped


def _stub_is_spec_valid(stub: SkillStub) -> bool:
    return bool(stub.description.strip()) and len(stub.description) <= SPEC_DESCRIPTION_MAX_LENGTH


def _walk_full(candidates: QuerySet[LLMSkill]) -> tuple[dict[str, FileTree], list[str], list[str]]:
    # Names and column byte counts only. Bodies and files load later, and only for skills that fit,
    # so a user with many or very large skills does not cost the worker more than the bundle cap.
    sized = list(
        candidates.values("id", "name").annotate(
            body_bytes=_OctetLength(F("body")),
            file_bytes=Coalesce(Sum(_OctetLength(F("files__content"))), 0),
        )
    )

    rows: dict[Any, LLMSkill] = {}
    trees: dict[str, FileTree] = {}
    dropped: list[str] = []
    skipped: list[str] = []
    total_bytes = 0
    capped = False
    for index, candidate in enumerate(sized):
        name = candidate["name"]
        if capped or len(trees) >= MAX_BUNDLE_SKILLS:
            capped = True
            dropped.append(name)
            continue
        # The stored bytes are a floor for the rendered tree, so a skill that fails here would fail
        # the exact check below too. Checking first keeps its content out of memory entirely.
        if total_bytes + candidate["body_bytes"] + candidate["file_bytes"] > MAX_BUNDLE_BYTES:
            capped = True
            dropped.append(name)
            continue
        if candidate["id"] not in rows:
            rows = LLMSkill.objects.in_bulk([c["id"] for c in sized[index : index + MAX_BUNDLE_SKILLS]])
        skill = rows[candidate["id"]]
        files = list(LLMSkillFile.objects.filter(skill=skill).order_by("path"))
        # The zip is unpacked into a home directory by a client that trusts it, so the archive
        # entry names must come from validated data. Current writes validate; legacy rows may not.
        if not SKILL_NAME_PATTERN.match(skill.name) or not _skill_files_are_tree_safe(files):
            skipped.append(name)
            continue
        export = skill_to_export(skill, files)
        if validate_for_export(export):
            skipped.append(name)
            continue
        tree = build_skill_tree(export)
        tree_bytes = file_tree_bytes(tree)
        if total_bytes + tree_bytes > MAX_BUNDLE_BYTES:
            capped = True
            dropped.append(name)
            continue
        total_bytes += tree_bytes
        trees[name] = tree
    return trees, dropped, skipped
