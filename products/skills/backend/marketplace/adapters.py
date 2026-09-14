"""ORM-aware bridge between ``LLMSkill`` rows and the Django-free packaging core.

Everything that touches the database for export/marketplace lives here, so the
serialization and git synthesis stay unit-testable without booting the app.
"""

from collections.abc import Iterator
from typing import Any, Literal, TypeVar

from django.core.cache import cache
from django.db.models import F, Func, IntegerField, Max, Q, QuerySet, TextField
from django.db.models.functions import Cast

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team, User

from ..api.skill_services import compute_spec_problems, skill_names_owned_by
from ..models.skills import LLMSkill, LLMSkillFile
from .git_smart_http import FileTree, SynthesizedRepo, synthesize_repo
from .packaging import (
    DEFAULT_BUNDLE_SKILLS,
    MAX_BUNDLE_SKILLS,
    SkillExport,
    SkillStub,
    archive_entry_bytes,
    build_marketplace_tree,
    build_skill_stub_tree,
    build_skill_tree,
    build_skills_bundle_zip,
    compute_plugin_version,
    file_tree_bytes,
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

# A full bundle carries skill content, so it is bounded by what a coding agent can usefully load,
# not by what the team owns. The count limit lives with the other bundle policy in packaging.
MAX_BUNDLE_BYTES = 5_000_000

# Gates every path that lists a user's store skills inside a sandbox: the bundle endpoint and the
# run-state stamp the task worker writes for the sandbox agent.
SANDBOX_SKILLS_FEATURE_FLAG = "skills-store-in-sandbox"


def sandbox_skills_flag_distinct_id(user: User) -> str:
    """The identity every consumer of ``SANDBOX_SKILLS_FEATURE_FLAG`` evaluates it with.

    A person-targeted or percentage rollout hashes this value, so the bundle endpoint and the task
    worker must agree on the fallback for a user with no ``distinct_id`` or they can disagree on
    whether the store is on.
    """
    return user.distinct_id or str(user.uuid)


# A heavy user can skip very many skills, so the walk keeps only a fixed-size sample of their names
# plus a running count — never a list proportional to the skip total. The warning logs that sample
# and count; the response header carries the count only.
_SKIPPED_LOG_SAMPLE_SIZE = 20


def load_skill_export(skill: LLMSkill) -> SkillExport:
    files = list(LLMSkillFile.objects.filter(skill=skill).order_by("path"))
    return skill.to_export(files)


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

    # Drop any skill that would synthesize a corrupt/uncloneable git tree (e.g. legacy rows that
    # predate the stricter path validation, or case-only collisions). One bad skill is skipped
    # rather than 500-ing the whole team's marketplace clone, and `spec_problems` on the skill tells
    # its author why. We also cap the cumulative content size: past the ceiling, remaining skills are
    # skipped so a pathological team can't OOM the clone.
    exports: list[SkillExport] = []
    skipped_unsafe_count = 0
    skipped_unsafe_sample: list[str] = []
    skipped_oversize: list[str] = []
    total_bytes = 0
    for skill in skills:
        files = files_by_skill.get(skill.id, [])
        if compute_spec_problems(skill.name, skill.description, [f.path for f in files]):
            skipped_unsafe_count = _record_skip(skipped_unsafe_count, skipped_unsafe_sample, skill.name)
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
        exports.append(skill.to_export(files))
    if skipped_unsafe_count:
        logger.warning(
            "skills_marketplace_skipped_unsafe_skills",
            team_id=team.id,
            skipped_count=skipped_unsafe_count,
            skills_sample=skipped_unsafe_sample,
        )
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
    dropped_count: int
    skipped_count: int


BundleContent = Literal["stub", "full"]


@frozen
class SkillStubSelection:
    """The discovery half of a user's store skills, newest first, plus what the walk left out."""

    stubs: list[SkillStub]
    dropped_count: int
    skipped_count: int


@frozen
class _BundleWalk:
    trees: dict[str, FileTree]
    dropped_count: int
    skipped_count: int
    skipped_sample: list[str]


@frozen
class _StubWalk:
    stubs: list[SkillStub]
    dropped_count: int
    skipped_count: int
    skipped_sample: list[str]


def _octet_length(expression: F | Cast) -> Func:
    return Func(expression, function="OCTET_LENGTH", output_field=IntegerField())


_Row = TypeVar("_Row")


def _candidate_batches(rows: "QuerySet[LLMSkill, _Row]") -> Iterator[_Row]:
    """Yield candidate rows in fixed-size slices so a user with thousands of skills never has them
    all in memory at once; the caller stops iterating once the bundle is capped.

    The slice size is the ceiling, not the caller's limit: skipped skills do not count toward the
    limit, so paging by a small limit would cost one query per skipped row.
    """
    offset = 0
    while True:
        batch = list(rows[offset : offset + MAX_BUNDLE_SKILLS])
        if not batch:
            return
        yield from batch
        offset += len(batch)


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
    team: Team,
    user: User,
    readable_skills: QuerySet[LLMSkill],
    content: BundleContent = "stub",
    limit: int = DEFAULT_BUNDLE_SKILLS,
) -> SkillBundle:
    """One zip of the skills a user created or owns, for unpacking into a skills directory.

    ``content="stub"`` writes one ``SKILL.md`` per skill with only its name and description and a
    body that tells the agent to fetch the real skill over MCP when it is invoked. That keeps the
    per-run payload to discovery metadata; skill content only moves when a skill is used.
    ``content="full"`` writes the whole skill: rendered ``SKILL.md``, bundled files and the Codex
    sidecar.

    ``readable_skills`` is the caller's access-filtered view of the team's skills. The walk only
    selects from it, so a skill the list endpoint would hide from the user stays out of the bundle.

    Newest first, at most ``limit`` skills; the caller chooses the limit, up to ``MAX_BUNDLE_SKILLS``.
    Skills that fail the spec check or carry a name or path the harness could not unpack safely are
    ``skipped``; they do not count toward the caps and are checked before them. The walk stops at
    the first skill that would cross the count or byte cap; everything after it is counted as
    dropped and never read. Scouts are excluded because the scout harness loads its own skill.
    """
    candidates = _bundle_candidates(team, user, readable_skills)
    limit = min(limit, MAX_BUNDLE_SKILLS)
    if content == "stub":
        stub_walk = _walk_stubs(candidates, limit)
        walk = _BundleWalk(
            trees={stub.name: build_skill_stub_tree(stub) for stub in stub_walk.stubs},
            dropped_count=stub_walk.dropped_count,
            skipped_count=stub_walk.skipped_count,
            skipped_sample=stub_walk.skipped_sample,
        )
    else:
        walk = _walk_full(candidates, limit)
    _log_walk(team, user, walk)

    return SkillBundle(
        zip_bytes=build_skills_bundle_zip(walk.trees),
        included=list(walk.trees),
        dropped_count=walk.dropped_count,
        skipped_count=walk.skipped_count,
    )


def select_skill_stubs(
    team: Team,
    user: User,
    readable_skills: QuerySet[LLMSkill],
    limit: int = DEFAULT_BUNDLE_SKILLS,
) -> SkillStubSelection:
    """The stubs a stub bundle would hold, without the zip, for a consumer that renders them itself.

    Same selection, order, caps and checks as ``build_skill_bundle(content="stub")``, so a sandbox
    that reads its stubs from run state lists exactly the skills a bundle download would install.
    """
    candidates = _bundle_candidates(team, user, readable_skills)
    walk = _walk_stubs(candidates, min(limit, MAX_BUNDLE_SKILLS))
    _log_walk(team, user, walk)
    return SkillStubSelection(stubs=walk.stubs, dropped_count=walk.dropped_count, skipped_count=walk.skipped_count)


def _log_walk(team: Team, user: User, walk: _BundleWalk | _StubWalk) -> None:
    if walk.skipped_count:
        logger.warning(
            "skills_bundle_skipped",
            team_id=team.id,
            user_id=user.id,
            skipped_count=walk.skipped_count,
            skills_sample=walk.skipped_sample,
        )
    if walk.dropped_count:
        logger.warning(
            "skills_bundle_dropped_over_cap", team_id=team.id, user_id=user.id, dropped_count=walk.dropped_count
        )


def _dropped_count(candidates: QuerySet[LLMSkill], included_count: int, skipped_count: int) -> int:
    # Every candidate the walk did not include or skip was dropped at the cap. One count query
    # instead of holding the tail of names in memory for a user with thousands of skills.
    return candidates.count() - included_count - skipped_count


def _record_skip(count: int, sample: list[str], name: str) -> int:
    """Bump the skip count and keep only a fixed-size sample of names, so the retained list never
    grows with the number of skipped skills. Returns the new count."""
    if len(sample) < _SKIPPED_LOG_SAMPLE_SIZE:
        sample.append(name)
    return count + 1


def _walk_stubs(candidates: QuerySet[LLMSkill], limit: int) -> _StubWalk:
    stubs: list[SkillStub] = []
    skipped_count = 0
    skipped_sample: list[str] = []
    for row in _candidate_batches(candidates.values("name", "description", "version")):
        if len(stubs) >= limit:
            return _StubWalk(
                stubs=stubs,
                dropped_count=_dropped_count(candidates, len(stubs), skipped_count),
                skipped_count=skipped_count,
                skipped_sample=skipped_sample,
            )
        name = row["name"]
        # A stub bundle writes only the generated SKILL.md, so a bundled-file path cannot break it.
        if compute_spec_problems(name, row["description"], []):
            skipped_count = _record_skip(skipped_count, skipped_sample, name)
            continue
        stubs.append(SkillStub(name=name, description=row["description"], version=row["version"]))
    return _StubWalk(stubs=stubs, dropped_count=0, skipped_count=skipped_count, skipped_sample=skipped_sample)


def _walk_full(candidates: QuerySet[LLMSkill], limit: int) -> _BundleWalk:
    # Names, descriptions and column byte counts only. A skill's row and files load one skill at a
    # time, and only once it has passed every check, so a user with many or very large skills does
    # not cost the worker more than the bundle cap. File sizes come from the per-skill path query
    # below rather than a join here, so the database never aggregates past the current slice.
    sized = candidates.values("id", "name", "description").annotate(
        body_bytes=_octet_length(F("body")),
        # metadata and allowed_tools render into SKILL.md and have no per-field size limit.
        meta_bytes=_octet_length(Cast(F("metadata"), TextField()))
        + _octet_length(Cast(F("allowed_tools"), TextField())),
    )

    trees: dict[str, FileTree] = {}
    skipped_count = 0
    skipped_sample: list[str] = []
    total_bytes = 0
    capped = False
    for candidate in _candidate_batches(sized):
        name = candidate["name"]
        if len(trees) >= limit:
            capped = True
            break
        # Skips are decided before the cap so an invalid skill never caps the bundle. The row-level
        # rules run first, off the columns already in hand, so a skill they reject costs no query.
        if compute_spec_problems(name, candidate["description"], []):
            skipped_count = _record_skip(skipped_count, skipped_sample, name)
            continue
        sized_files = list(
            LLMSkillFile.objects.filter(skill_id=candidate["id"])
            .annotate(content_bytes=_octet_length(F("content")))
            .values_list("path", "content_bytes")
        )
        if compute_spec_problems(name, candidate["description"], [path for path, _ in sized_files]):
            skipped_count = _record_skip(skipped_count, skipped_sample, name)
            continue
        # The stored bytes are a floor for the rendered tree, so a skill that fails here would fail
        # the exact check below too. Checking first keeps its content out of memory entirely.
        # Charge the archived member name (build_skills_bundle_zip nests every entry under
        # <name>/), not just the relative path, so long names count against the cap.
        file_bytes = sum(archive_entry_bytes(f"{name}/{path}", content_bytes) for path, content_bytes in sized_files)
        if total_bytes + candidate["body_bytes"] + candidate["meta_bytes"] + file_bytes > MAX_BUNDLE_BYTES:
            capped = True
            break
        skill = candidates.filter(id=candidate["id"]).first()
        if skill is None:
            # Archived or superseded since the slice was read. The closing count query will not see
            # it either, so it is neither included, skipped nor dropped.
            continue
        files = list(LLMSkillFile.objects.filter(skill=skill).order_by("path"))
        tree = build_skill_tree(skill.to_export(files))
        tree_bytes = file_tree_bytes(tree, prefix=f"{name}/")
        if total_bytes + tree_bytes > MAX_BUNDLE_BYTES:
            capped = True
            break
        total_bytes += tree_bytes
        trees[name] = tree
    dropped_count = _dropped_count(candidates, len(trees), skipped_count) if capped else 0
    return _BundleWalk(
        trees=trees, dropped_count=dropped_count, skipped_count=skipped_count, skipped_sample=skipped_sample
    )
