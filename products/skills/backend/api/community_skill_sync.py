from typing import Any

from django.db import transaction
from django.utils import timezone

import requests
import structlog

from ..models.community_skills import CommunitySkill, CommunitySkillFile
from .skill_services import MAX_SKILL_BODY_BYTES, MAX_SKILL_FILE_BYTES, MAX_SKILL_FILE_COUNT

logger = structlog.get_logger(__name__)

COMMUNITY_SKILLS_REPO = "PostHog/community-skills"
COMMUNITY_SKILLS_BRANCH = "main"
COMMUNITY_SKILLS_REGISTRY_URL = (
    f"https://raw.githubusercontent.com/{COMMUNITY_SKILLS_REPO}/{COMMUNITY_SKILLS_BRANCH}/registry.json"
)
COMMUNITY_SKILLS_SYNC_TIMEOUT_SECONDS = 30


def _validate_entry_within_caps(entry: dict[str, Any]) -> None:
    """Reject oversized registry entries before persisting, mirroring the skill import caps.

    The registry is built in a review-gated repo, but the same body/file caps the normal
    import path enforces are cheap insurance against one bad entry bloating Postgres.
    """
    body = entry.get("body", "") or ""
    if len(body.encode("utf-8")) > MAX_SKILL_BODY_BYTES:
        raise ValueError(f"body exceeds the {MAX_SKILL_BODY_BYTES} byte limit")

    files = entry.get("files", []) or []
    if len(files) > MAX_SKILL_FILE_COUNT:
        raise ValueError(f"has more than {MAX_SKILL_FILE_COUNT} files")
    for f in files:
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

    defaults: dict[str, Any] = {
        "name": entry["name"],
        "description": entry["description"],
        "body": entry.get("body", ""),
        "license": entry.get("license", ""),
        "compatibility": entry.get("compatibility", ""),
        "allowed_tools": entry.get("allowed_tools", []),
        "metadata": entry.get("metadata", {}),
        "tags": entry.get("tags", []),
        "trust_tier": entry.get("trust_tier", "community"),
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
