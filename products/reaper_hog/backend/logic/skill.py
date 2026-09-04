import re
import hashlib
import logging
from pathlib import Path

from django.db import IntegrityError, transaction

import yaml

from posthog.dataclasses import frozen

from products.reaper_hog.backend.logic.constants import VERIFICATION_SKILL_NAME
from products.skills.backend.models.skills import LLMSkill

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
SEEDED_BY = "reaper_hog"
SKILL_CATEGORY = "reaper_hog"
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@frozen
class CanonicalSkill:
    name: str
    description: str
    body: str
    content_hash: str


@frozen
class PinnedSkill:
    name: str
    version: int


def load_canonical_skill(name: str = VERIFICATION_SKILL_NAME, *, skills_dir: Path = SKILLS_DIR) -> CanonicalSkill:
    text = (skills_dir / name / "SKILL.md").read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    if match is None:
        raise ValueError(f"SKILL.md for {name} has no frontmatter")
    frontmatter = yaml.safe_load(match.group(1)) or {}
    if frontmatter.get("name") != name:
        raise ValueError(f"SKILL.md frontmatter name {frontmatter.get('name')!r} does not match {name!r}")
    body = text[match.end() :].strip()
    description = str(frontmatter.get("description", "")).strip()
    digest = hashlib.sha256(f"{description}\n{body}".encode()).hexdigest()
    return CanonicalSkill(name=name, description=description, body=body, content_hash=digest)


def sync_skill(team_id: int, canonical: CanonicalSkill) -> PinnedSkill:
    rows = list(LLMSkill.objects.filter(team_id=team_id, name=canonical.name).order_by("-version"))
    live = next((row for row in rows if not row.deleted and row.is_latest), None)
    if live is None:
        version = rows[0].version + 1 if rows else 1
        return _create_version(team_id, canonical, version) or _reload(team_id, canonical.name)
    if (live.metadata or {}).get("seeded_by") != SEEDED_BY:
        return PinnedSkill(name=live.name, version=live.version)
    if (live.metadata or {}).get("canonical_hash") == canonical.content_hash:
        return PinnedSkill(name=live.name, version=live.version)
    try:
        with transaction.atomic():
            locked = LLMSkill.objects.select_for_update().get(pk=live.pk)
            locked.is_latest = False
            locked.save(update_fields=["is_latest", "updated_at"])
            created = _insert(team_id, canonical, locked.version + 1)
    except IntegrityError:
        logger.info("reaper_hog: concurrent skill update won the race; reusing it", extra={"team_id": team_id})
        return _reload(team_id, canonical.name)
    return created


def sync_verification_skill(team_id: int) -> PinnedSkill:
    return sync_skill(team_id, load_canonical_skill())


def _create_version(team_id: int, canonical: CanonicalSkill, version: int) -> PinnedSkill | None:
    try:
        with transaction.atomic():
            return _insert(team_id, canonical, version)
    except IntegrityError:
        logger.info("reaper_hog: concurrent skill create won the race; reusing it", extra={"team_id": team_id})
        return None


def _insert(team_id: int, canonical: CanonicalSkill, version: int) -> PinnedSkill:
    LLMSkill.objects.create(
        team_id=team_id,
        name=canonical.name,
        description=canonical.description,
        body=canonical.body,
        metadata={"seeded_by": SEEDED_BY, "canonical_hash": canonical.content_hash},
        category=SKILL_CATEGORY,
        version=version,
        is_latest=True,
    )
    return PinnedSkill(name=canonical.name, version=version)


def _reload(team_id: int, name: str) -> PinnedSkill:
    live = LLMSkill.objects.get(team_id=team_id, name=name, deleted=False, is_latest=True)
    return PinnedSkill(name=live.name, version=live.version)
