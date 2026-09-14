from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DataError, IntegrityError, transaction
from django.db.models import Field, Model
from django.utils import timezone

import structlog
from rest_framework.serializers import ValidationError as DRFValidationError

from posthog.egress.github.transport import github_request

from ..marketplace.packaging import SPEC_DESCRIPTION_MAX_LENGTH
from ..models.community_skills import CommunitySkill, CommunitySkillFile, CommunitySkillTrustTier
from .skill_serializers import validate_skill_file_path
from .skill_services import (
    MAX_SKILL_BODY_BYTES,
    MAX_SKILL_FILE_BYTES,
    MAX_SKILL_FILE_COUNT,
    RESERVED_SKILL_NAMES,
    SKILL_NAME_PATTERN,
)

logger = structlog.get_logger(__name__)

_VALID_TRUST_TIERS = set(CommunitySkillTrustTier.values)
DEFAULT_FILE_CONTENT_TYPE = "text/plain"
# CharField columns that raise DataError past their max_length — checked before persisting.
_CHECKED_CHAR_FIELDS = (
    "slug",
    "name",
    "description",
    "license",
    "compatibility",
    "author_handle",
    "github_url",
    "source_sha",
)


def _text(container: dict[str, Any], key: str, label: str, default: str = "") -> str:
    """Read a text field, rejecting non-strings before any default is applied.

    An `or <default>` fallback masks a *falsy* non-string (``False``, ``0``, ``[]``): it satisfies
    a later isinstance check as ``""`` while the raw value is what reaches the column, and
    Char/TextField stores its repr (``"False"``, ``"0"``, ``"[]"``). Both validation and
    persistence go through here so they can't disagree about what the value is. Absent and
    explicit-null both mean "use the default".
    """
    raw = container.get(key)
    if raw is None:
        return default
    if not isinstance(raw, str):
        raise ValueError(f"{label} must be a string")
    return raw


def _field_max_length(model: type[Model], field_name: str) -> int | None:
    # _meta.get_field returns Field | ForeignObjectRel | GenericForeignKey; only concrete
    # Fields carry max_length. All names we pass here are CharFields, so narrow to Field.
    field = model._meta.get_field(field_name)
    return field.max_length if isinstance(field, Field) else None


COMMUNITY_SKILLS_REPO = "PostHog/community-skills"
COMMUNITY_SKILLS_BRANCH = "main"
COMMUNITY_SKILLS_REGISTRY_URL = (
    f"https://raw.githubusercontent.com/{COMMUNITY_SKILLS_REPO}/{COMMUNITY_SKILLS_BRANCH}/registry.json"
)
COMMUNITY_SKILLS_SYNC_TIMEOUT_SECONDS = 30


def _validate_entry_shape(entry: dict[str, Any]) -> None:
    """Reject entries whose field shapes would break catalog rendering or install.

    The registry is generated in a review-gated repo, but a single mistyped field (a scalar
    ``metadata``, a non-list ``tags``, a slug that DRF's lookup regex can't route) would
    otherwise 500 the whole list/detail page or the install copy. Raising ValueError isolates
    the failure to the one bad entry (the sync loop's per-entry ``except`` catches it).
    """
    slug = entry.get("slug", "")
    # The slug is both the catalog URL segment and the default installed-skill name, so it must
    # satisfy the skill-name rules — lowercase alnum + single hyphens, not reserved. This also
    # keeps DRF's default lookup regex (which rejects '.'/'/') able to route detail/install URLs,
    # and means the default-name install can never raise an uncaught name ValidationError.
    # fullmatch, not match: `$` also matches just before a trailing newline, so `match` would
    # accept "valid-skill\n" and persist the newline into the URL segment and install name.
    if (
        not isinstance(slug, str)
        or not SKILL_NAME_PATTERN.fullmatch(slug)
        or "--" in slug
        or slug.lower() in RESERVED_SKILL_NAMES
    ):
        raise ValueError(f"slug '{slug}' is not a valid, routable skill identifier")

    # Blank passes both the type and length checks but leaves an unusable entry: a nameless card in
    # the catalog, and a blank description that `marketplace.packaging.validate_for_export` refuses,
    # so the skill installs and then can't be exported. The install path rejects it too.
    for required in ("name", "description"):
        if not _text(entry, required, f"'{required}'").strip():
            raise ValueError(f"'{required}' is required and must be non-blank")

    metadata = entry.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")

    # A falsy non-list (`{}`, `false`, `0`, `""`) must not be normalized to "no files": the upsert
    # deletes the skill's existing files before recreating them, so a mistyped `files` on an entry
    # with a changed source_sha would strip every bundled file from a live catalog skill and still
    # report the sync as successful. Absent/null legitimately mean "no files".
    files = entry.get("files")
    if files is not None and not isinstance(files, list):
        raise ValueError("files must be a list")

    tags = entry.get("tags")
    if tags is not None and (not isinstance(tags, list) or not all(isinstance(t, str) for t in tags)):
        raise ValueError("tags must be a list of strings")

    allowed_tools = entry.get("allowed_tools")
    if allowed_tools is not None:
        if not isinstance(allowed_tools, list) or not all(isinstance(t, str) for t in allowed_tools):
            raise ValueError("allowed_tools must be a list of strings")
        # The Agent Skills spec serializes allowed-tools as one space-separated string, so a name
        # with whitespace would silently fracture into multiple tools on export/round-trip.
        if any(any(ch.isspace() for ch in t) for t in allowed_tools):
            raise ValueError("allowed_tools names cannot contain whitespace")


def _validate_entry_within_caps(entry: dict[str, Any]) -> None:
    """Reject entries that would violate a DB constraint before persisting.

    The registry is built in a review-gated repo, but a single entry that overflows a column
    (oversized body/file, an overlong slug/name, a duplicate file path) would otherwise raise
    DataError/IntegrityError mid-loop — aborting the whole sync and skipping the soft-delete
    reconciliation. Raising ValueError here keeps that failure isolated to the one bad entry.
    """
    body = _text(entry, "body", "body")
    if len(body.encode("utf-8")) > MAX_SKILL_BODY_BYTES:
        raise ValueError(f"body exceeds the {MAX_SKILL_BODY_BYTES} byte limit")

    for field in _CHECKED_CHAR_FIELDS:
        value = _text(entry, field, f"'{field}'")
        max_length = SPEC_DESCRIPTION_MAX_LENGTH if field == "description" else _field_max_length(CommunitySkill, field)
        if max_length is not None and len(value) > max_length:
            raise ValueError(f"'{field}' exceeds the {max_length} character limit")

    files = entry.get("files", []) or []
    if len(files) > MAX_SKILL_FILE_COUNT:
        raise ValueError(f"has more than {MAX_SKILL_FILE_COUNT} files")
    path_max = _field_max_length(CommunitySkillFile, "path")
    seen_paths: set[str] = set()
    for f in files:
        raw_path = _text(f, "path", "file path")
        # Same invariant the skill create/import paths enforce: traversal, absolute, reserved and
        # backslash spellings produce corrupt git/export trees. Normalizing here also means dedup
        # compares canonical paths, so `references\g.md` and `references/g.md` can't both land.
        try:
            path = validate_skill_file_path(raw_path)
        except DRFValidationError as err:
            raise ValueError(f"file path '{raw_path}' is invalid: {err.detail}") from err
        if path_max is not None and len(path) > path_max:
            raise ValueError(f"file path '{path}' exceeds the {path_max} character limit")
        # Case-insensitive, matching `_skill_files_are_tree_safe`: two paths differing only by case
        # collide on a case-insensitive filesystem, and that check silently drops the whole skill
        # from a team's marketplace clone. Cheaper to reject the entry than to ship a skill that
        # installs fine and then vanishes from the generated tree.
        if path.lower() in seen_paths:
            raise ValueError(f"duplicate file path '{path}'")
        seen_paths.add(path.lower())
        content_type = _text(f, "content_type", f"file '{path}' content_type", DEFAULT_FILE_CONTENT_TYPE)
        ct_max = _field_max_length(CommunitySkillFile, "content_type")
        if ct_max is not None and len(content_type) > ct_max:
            raise ValueError(f"file '{path}' content_type exceeds the {ct_max} character limit")
        content = _text(f, "content", f"file '{path}' content")
        if len(content.encode("utf-8")) > MAX_SKILL_FILE_BYTES:
            raise ValueError(f"file '{path}' exceeds the {MAX_SKILL_FILE_BYTES} byte limit")


def _upsert_community_skill(entry: dict[str, Any]) -> bool:
    """Upsert a single registry entry. Returns True if the row was created or updated."""
    slug = entry["slug"]
    _validate_entry_shape(entry)
    _validate_entry_within_caps(entry)
    # Read through _text after validation so the value compared against the stored sha (and every
    # value persisted below) is the same coerced string the caps check approved.
    source_sha = _text(entry, "source_sha", "'source_sha'")

    existing = CommunitySkill.objects.filter(slug=slug).first()
    if existing is not None and existing.source_sha and existing.source_sha == source_sha and not existing.deleted:
        return False

    # Model choices aren't DB-enforced, so an unknown tier would persist raw and break consumers
    # that coerce it back to CommunitySkillTrustTier — fall back to the least-privileged tier.
    trust_tier = entry.get("trust_tier") or CommunitySkillTrustTier.COMMUNITY.value
    if trust_tier not in _VALID_TRUST_TIERS:
        logger.warning("community_skills_sync_unknown_trust_tier", slug=slug, trust_tier=trust_tier)
        trust_tier = CommunitySkillTrustTier.COMMUNITY.value

    defaults: dict[str, Any] = {
        # name/description stay subscripted: they're required, and a missing one must raise
        # KeyError so the entry is isolated rather than persisted with empty visible text.
        "name": entry["name"],
        "description": entry["description"],
        "body": _text(entry, "body", "body"),
        "license": _text(entry, "license", "'license'"),
        "compatibility": _text(entry, "compatibility", "'compatibility'"),
        # `or <empty>` rather than a .get default: an explicitly-null field in the registry makes
        # .get return None, which these non-nullable JSON columns reject at insert time.
        "allowed_tools": entry.get("allowed_tools") or [],
        "metadata": entry.get("metadata") or {},
        # Store tags lowercased so the tag/search filters match regardless of how a contributor
        # capitalized them in frontmatter (_validate_entry_shape guarantees a list of strings).
        "tags": [t.lower() for t in (entry.get("tags") or [])],
        "trust_tier": trust_tier,
        "author_handle": _text(entry, "author_handle", "'author_handle'"),
        "github_url": _text(entry, "github_url", "'github_url'"),
        "source_sha": source_sha,
        "deleted": False,
    }
    if entry.get("published_at"):
        defaults["published_at"] = entry["published_at"]

    with transaction.atomic():
        skill, _ = CommunitySkill.objects.update_or_create(slug=slug, defaults=defaults)
        if skill.published_at is None:
            CommunitySkill.objects.filter(pk=skill.pk).update(published_at=timezone.now())

        skill.files.all().delete()
        files = entry.get("files", [])
        if files:
            CommunitySkillFile.objects.bulk_create(
                [
                    CommunitySkillFile(
                        # Store the canonical form the caps check produced, not the raw spelling.
                        path=validate_skill_file_path(_text(f, "path", "file path")),
                        skill=skill,
                        content=_text(f, "content", "file content"),
                        content_type=_text(f, "content_type", "file content_type", DEFAULT_FILE_CONTENT_TYPE),
                    )
                    for f in files
                ]
            )
    return True


def sync_community_skills_from_github(registry_url: str = COMMUNITY_SKILLS_REGISTRY_URL) -> dict[str, int]:
    """Pull the community-skills registry and reconcile the local read-model.

    The registry.json is generated in the repo's CI and embeds each skill's content, so a
    single fetch is enough. Skills missing from the registry are soft-deleted. Returns a
    summary of {synced, skipped, removed} counts.
    """
    # Identity-blind GitHub egress: an unauthenticated CDN fetch with no installation to meter,
    # so it records request volume only and skips the limiter, but still goes through the gated,
    # recorded transport rather than hand-rolled requests.
    response = github_request(
        "GET",
        registry_url,
        source="community_skills",
        installation_id=None,
        timeout=COMMUNITY_SKILLS_SYNC_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    entries = payload.get("skills", [])

    # Fail closed on malformed/empty payloads: a missing/empty `skills` key (bad generated
    # registry, proxy error, rate-limit body) would otherwise soft-delete the entire catalog.
    if not isinstance(entries, list):
        raise ValueError("Registry payload 'skills' must be a list")
    if not entries:
        logger.warning("community_skills_sync_skipped_empty_registry")
        return {"synced": 0, "skipped": 0, "removed": 0}

    synced = 0
    skipped = 0
    processed_ok = 0
    seen_slugs: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug")
        # Must be a string before it can go in a set: a truthy-but-unhashable slug (object/array
        # from a malformed registry) would raise TypeError here, outside the per-entry boundary,
        # and abort the whole sync. Full slug validation still happens inside the upsert.
        if not slug or not isinstance(slug, str):
            # Unidentifiable: we can't tell which catalog row it meant, so it can't be marked seen.
            # Logged because it's otherwise invisible — it never reaches the per-entry handler.
            logger.warning("community_skills_sync_unidentifiable_entry", slug_type=type(slug).__name__)
            continue
        # Mark the slug seen before upserting so a malformed entry can't soft-delete the
        # existing row for a skill that's still present in the registry.
        seen_slugs.add(slug)
        try:
            created_or_updated = _upsert_community_skill(entry)
        except (KeyError, ValueError, TypeError, AttributeError, DjangoValidationError, IntegrityError, DataError):
            # One bad entry (missing/oversized/mistyped field, or a constraint violation) must not
            # abort the whole loop or skip the reconciliation below. Each upsert runs in its own
            # atomic block, so the failed insert has already rolled back cleanly by the time we
            # catch. Only entry-local constraint errors are caught: operational failures
            # (connection loss, failover, statement timeout) are not one bad entry, and swallowing
            # them would report a successful sync while the catalog silently went stale.
            logger.warning("community_skills_sync_skipped_invalid_entry", slug=slug, exc_info=True)
            skipped += 1
            continue
        processed_ok += 1
        if created_or_updated:
            synced += 1
        else:
            skipped += 1

    # Fail-safe: only reconcile once at least one entry processed cleanly. A registry that parsed
    # but yielded zero healthy entries (schema change, generator bug, every entry malformed) must
    # not soft-delete the catalog — even when the malformed entries carried slugs.
    if not processed_ok:
        logger.warning("community_skills_sync_skipped_no_healthy_entries", entry_count=len(entries))
        return {"synced": synced, "skipped": skipped, "removed": 0}

    removed = CommunitySkill.objects.filter(deleted=False).exclude(slug__in=seen_slugs).update(deleted=True)

    logger.info("community_skills_synced", synced=synced, skipped=skipped, removed=removed, total=len(entries))
    return {"synced": synced, "skipped": skipped, "removed": removed}
