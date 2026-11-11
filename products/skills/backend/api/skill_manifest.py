"""Resource manifests for the MCP Skills extension: every file a host downloads, with its digest.

A host verifies each file it reads against the SHA-256 and byte size the listing gave it, and
rejects the skill when they disagree. So the manifest reads the digests the store stamped on write
and never renders or loads content: a manifest that hashed on read could describe bytes the store
no longer serves.
"""

from collections.abc import Sequence
from uuid import UUID

from django.db import models

import structlog

from posthog.dataclasses import frozen

from ..marketplace.packaging import MCP_MAX_SKILL_BYTES, MCP_MAX_SKILL_FILES, frontmatter_document
from ..models.skills import LLMSkill, LLMSkillFile
from .skill_services import compute_spec_problems

logger = structlog.get_logger(__name__)

SKILL_MD_PATH = "SKILL.md"
SKILL_MD_CONTENT_TYPE = "text/markdown"


class SkillUnservableReason(models.TextChoices):
    TOO_MANY_FILES = "too_many_files", "Too many files"
    TOO_LARGE = "too_large", "Too large"
    DIGEST_MISSING = "digest_missing", "Digest missing"
    SPEC_PROBLEMS = "spec_problems", "Spec problems"


@frozen
class SkillManifestResource:
    path: str
    sha256: str | None
    size: int | None
    content_type: str


@frozen
class SkillManifest:
    name: str
    version: int
    frontmatter: dict[str, object]
    resources: list[SkillManifestResource]
    file_count: int
    total_size: int
    servable: bool
    unservable_reasons: list[SkillUnservableReason]


def build_skill_manifests(skills: Sequence[LLMSkill]) -> list[SkillManifest]:
    """One manifest per skill, in the order given, from one query for every bundled file row.

    The skills may be loaded with ``body`` deferred: nothing here reads it.
    """
    files_by_skill_id: dict[UUID, list[LLMSkillFile]] = {}
    file_rows = (
        LLMSkillFile.objects.filter(skill__in=skills)
        .only("skill_id", "path", "content_type", "content_size", "content_sha256")
        .order_by("path")
    )
    for file_row in file_rows:
        files_by_skill_id.setdefault(file_row.skill_id, []).append(file_row)

    manifests = [_build_manifest(skill, files_by_skill_id.get(skill.id, [])) for skill in skills]
    missing = [m.name for m in manifests if SkillUnservableReason.DIGEST_MISSING in m.unservable_reasons]
    if missing:
        logger.warning("llma_skill_manifest_digest_missing", skill_names=missing)
    return manifests


def _build_manifest(skill: LLMSkill, files: list[LLMSkillFile]) -> SkillManifest:
    resources = [
        SkillManifestResource(
            path=SKILL_MD_PATH,
            sha256=skill.skill_md_sha256,
            size=skill.skill_md_size,
            content_type=SKILL_MD_CONTENT_TYPE,
        ),
        *(
            SkillManifestResource(
                path=file_row.path,
                sha256=file_row.content_sha256,
                size=file_row.content_size,
                content_type=file_row.content_type,
            )
            for file_row in files
        ),
    ]
    file_count = len(resources)
    total_size = sum(resource.size or 0 for resource in resources)

    reasons: list[SkillUnservableReason] = []
    if file_count > MCP_MAX_SKILL_FILES:
        reasons.append(SkillUnservableReason.TOO_MANY_FILES)
    if total_size > MCP_MAX_SKILL_BYTES:
        reasons.append(SkillUnservableReason.TOO_LARGE)
    if any(resource.sha256 is None or resource.size is None for resource in resources):
        reasons.append(SkillUnservableReason.DIGEST_MISSING)
    if compute_spec_problems(skill.name, skill.description, [file_row.path for file_row in files]):
        reasons.append(SkillUnservableReason.SPEC_PROBLEMS)

    return SkillManifest(
        name=skill.name,
        version=skill.version,
        frontmatter=frontmatter_document(skill.to_export(include_body=False)),
        resources=resources,
        file_count=file_count,
        total_size=total_size,
        servable=not reasons,
        unservable_reasons=reasons,
    )
