from typing import Any

from django.db import transaction
from django.utils import timezone

import requests
import structlog

from ..models.community_skills import CommunitySkill, CommunitySkillFile, CommunitySkillTrustTier
from .skill_services import MAX_SKILL_BODY_BYTES, MAX_SKILL_FILE_BYTES, MAX_SKILL_FILE_COUNT

logger = structlog.get_logger(__name__)

_VALID_TRUST_TIERS = set(CommunitySkillTrustTier.values)
# CharField columns that raise DataError past their max_length — checked before persisting.
_CHECKED_CHAR_FIELDS = ("slug", "name", "description", "license", "compatibility", "author_handle", "github_url")

COMMUNITY_SKILLS_REPO = "PostHog/community-skills"
COMMUNITY_SKILLS_BRANCH = "main"
COMMUNITY_SKILLS_REGISTRY_URL = (
    f"https://raw.githubusercontent.com/{COMMUNITY_SKILLS_REPO}/{COMMUNITY_SKILLS_BRANCH}/registry.json"
)
COMMUNITY_SKILLS_SYNC_TIMEOUT_SECONDS = 30


def _validate_entry_within_caps(entry: dict[str, Any]) -> None:
    """Reject entries that would violate a DB constraint before persisting.

    The registry is built in a review-gated repo, but a single entry that overflows a column
    (oversized body/file, an overlong slug/name, a duplicate file path) would otherwise raise
    DataError/IntegrityError mid-loop — aborting the whole sync and skipping the soft-delete
    reconciliation. Raising ValueError here keeps that failure isolated to the one bad entry.
    """
    body = entry.get("body", "") or ""
    if len(body.encode("utf-8")) > MAX_SKILL_BODY_BYTES:
        raise ValueError(f"body exceeds the {MAX_SKILL_BODY_BYTES} byte limit")

    for field in _CHECKED_CHAR_FIELDS:
        value = entry.get(field, "") or ""
        max_length = CommunitySkill._meta.get_field(field).max_length
        if max_length is not None and len(value) > max_length:
            raise ValueError(f"'{field}' exceeds the {max_length} character limit")

    files = entry.get("files", []) or []
    if len(files) > MAX_SKILL_FILE_COUNT:
        raise ValueError(f"has more than {MAX_SKILL_FILE_COUNT} files")
    path_max = CommunitySkillFile._meta.get_field("path").max_length
    seen_paths: set[str] = set()
    for f in files:
        path = f.get("path", "") or ""
        if path_max is not None and len(path) > path_max:
            raise ValueError(f"file path '{path}' exceeds the {path_max} character limit")
        if path in seen_paths:
            raise ValueError(f"duplicate file path '{path}'")
        seen_paths.add(path)
        content = f.get("content", "") or ""
        if len(content.encode("utf-8")) > MAX_SKILL_FILE_BYTES:
            raise ValueError(f"file '{f.get('path')}' exceeds the {MAX_SKILL_FILE_BYTES} byte limit")


def _upsert_community_skill(entry: dict[str, Any]) -> bool:
    """Upsert a single registry entry. Returns True if the row was created or updated."""
    slug = entry["slug"]
    source_sha = entry.get("source_sha", "")
    _validate_entry_within_caps(entry)

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
        "name": entry["name"],
        "description": entry["description"],
        "body": entry.get("body", ""),
        "license": entry.get("license", ""),
        "compatibility": entry.get("compatibility", ""),
        "allowed_tools": entry.get("allowed_tools", []),
        "metadata": entry.get("metadata", {}),
        "tags": entry.get("tags", []),
        "trust_tier": trust_tier,
        "author_handle": entry.get("author_handle", ""),
        "github_url": entry.get("github_url", ""),
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
                        skill=skill,
                        path=f["path"],
                        content=f.get("content", ""),
                        content_type=f.get("content_type", "text/plain"),
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
    response = requests.get(registry_url, timeout=COMMUNITY_SKILLS_SYNC_TIMEOUT_SECONDS)
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
    seen_slugs: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug")
        if not slug:
            continue
        # Mark the slug seen before upserting so a malformed entry can't soft-delete the
        # existing row for a skill that's still present in the registry.
        seen_slugs.add(slug)
        try:
            created_or_updated = _upsert_community_skill(entry)
        except (KeyError, ValueError, TypeError):
            # One bad entry (missing required field, oversized payload) must not abort the
            # whole loop or skip the soft-delete reconciliation below.
            logger.warning("community_skills_sync_skipped_invalid_entry", slug=slug, exc_info=True)
            skipped += 1
            continue
        if created_or_updated:
            synced += 1
        else:
            skipped += 1

    # Fail-safe: a non-empty registry that parsed into zero valid slugs (schema change, generator
    # bug, every entry malformed) must not soft-delete the entire catalog — skip reconciliation.
    if not seen_slugs:
        logger.warning("community_skills_sync_skipped_no_valid_slugs", entry_count=len(entries))
        return {"synced": synced, "skipped": skipped, "removed": 0}

    removed = CommunitySkill.objects.filter(deleted=False).exclude(slug__in=seen_slugs).update(deleted=True)

    logger.info("community_skills_synced", synced=synced, skipped=skipped, removed=removed, total=len(entries))
    return {"synced": synced, "skipped": skipped, "removed": removed}
