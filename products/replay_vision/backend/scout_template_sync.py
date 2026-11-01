"""Keeps scanner scouts created from a template on the template's latest text.

A scout is claimed when its text is exactly what a template rendered. On every sync, a claimed scout whose
text still matches the hash recorded at its last write gets the current template text as a new skill
version. A scout someone has edited no longer matches, so the sync leaves it alone.
"""

import re
import uuid
import hashlib

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.scout_source import SCOUT_SOURCE_PRODUCT
from products.replay_vision.backend.scout_template_history import LEGACY_TEMPLATE_BODY_HASHES
from products.replay_vision.backend.scout_templates import (
    SYNCED_TEMPLATE_KEYS,
    ScoutTemplateKey,
    render_template_body,
    template_key_from_skill_name,
)
from products.signals.backend.facade import api as signals_facade

logger = structlog.get_logger(__name__)

# Prefixes the template record, so a record another product wrote is never read as a Replay Vision key.
TEMPLATE_RECORD_PREFIX = "replay_vision_scanner_scout:"


@frozen
class TemplateSyncResult:
    updated: int
    claimed: int
    edited: int
    failed: int


def _synced_key(value: str | None) -> ScoutTemplateKey | None:
    if value not in ScoutTemplateKey.values:
        return None
    key = ScoutTemplateKey(value)
    return key if key in SYNCED_TEMPLATE_KEYS else None


def _key_from_record(record: str | None) -> ScoutTemplateKey | None:
    if not record or not record.startswith(TEMPLATE_RECORD_PREFIX):
        return None
    return _synced_key(record.removeprefix(TEMPLATE_RECORD_PREFIX))


def _is_legacy_template_body(key: ScoutTemplateKey, body: str, scanner_id: str) -> bool:
    normalized = re.sub(re.escape(scanner_id), "{scanner_id}", body, flags=re.IGNORECASE)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() in LEGACY_TEMPLATE_BODY_HASHES.get(key, frozenset())


def _claim(*, team_id: int, skill_name: str, version: int, key: ScoutTemplateKey) -> bool:
    return signals_facade.set_source_scout_template(
        team_id=team_id, skill_name=skill_name, version=version, template=f"{TEMPLATE_RECORD_PREFIX}{key.value}"
    )


def claim_template_scout(
    *, team_id: int, skill_name: str, template_key: str | None, body: str, scanner: ReplayScanner
) -> bool:
    """Claim a new scout for template sync when its text is exactly what the template renders for the scanner."""
    key = _synced_key(template_key)
    if key is None or render_template_body(key, str(scanner.id), scanner.scanner_type) != body:
        return False
    return _claim(team_id=team_id, skill_name=skill_name, version=1, key=key)


def _scanner_types(skills: list[signals_facade.SourceScoutSkill]) -> dict[tuple[int, str], str]:
    """Each scout's scanner type, keyed by the scout's team and scanner id.

    Scouts live on the canonical team while a scanner can sit on one of its environments, so a scanner only
    counts for a scout when its team, or that team's parent, is the scout's team.
    """
    team_ids = {skill.team_id for skill in skills}
    canonical = {team_id: team_id for team_id in team_ids}
    canonical.update(Team.objects.filter(parent_team_id__in=team_ids).values_list("id", "parent_team_id"))
    ids = []
    for skill in skills:
        try:
            ids.append(uuid.UUID(skill.source_id))
        except ValueError:
            continue
    # Cross-team by design: a system sweep over every team's scouts, each scanner matched to its scout's team below.
    # nosemgrep: idor-lookup-without-team
    rows = ReplayScanner.objects.filter(id__in=ids, team_id__in=canonical).values_list("id", "team_id", "scanner_type")
    return {(canonical[team_id], str(scanner_id)): scanner_type for scanner_id, team_id, scanner_type in rows}


def _sync_one(skill: signals_facade.SourceScoutSkill, scanner_type: str) -> str | None:
    """Bring one scout up to date, returning what happened to it, or None when nothing did."""
    scanner_id = skill.source_id.lower()
    key = _key_from_record(skill.template)
    if key is None:
        # A scout created before claiming existed: claim it when its text is a template's, untouched.
        key = template_key_from_skill_name(skill.skill_name)
        if key not in SYNCED_TEMPLATE_KEYS or not (
            skill.body == render_template_body(key, scanner_id, scanner_type)
            or _is_legacy_template_body(key, skill.body, scanner_id)
        ):
            return None
        claimed = _claim(team_id=skill.team_id, skill_name=skill.skill_name, version=skill.version, key=key)
        return "claimed" if claimed else None
    if signals_facade.source_scout_body_hash(skill.body) != skill.template_hash:
        return "edited"
    body = render_template_body(key, scanner_id, scanner_type)
    if body is None or body == skill.body:
        return None
    published = signals_facade.publish_source_scout_body(
        team_id=skill.team_id,
        skill_name=skill.skill_name,
        base_version=skill.version,
        body=body,
        template=f"{TEMPLATE_RECORD_PREFIX}{key.value}",
    )
    return "updated" if published else None


def sync_template_scouts() -> TemplateSyncResult:
    counts = {"updated": 0, "claimed": 0, "edited": 0, "failed": 0}
    skills = signals_facade.source_scout_skills(SCOUT_SOURCE_PRODUCT)
    scanner_types = _scanner_types(skills)
    for skill in skills:
        scanner_type = scanner_types.get((skill.team_id, skill.source_id.lower()))
        if scanner_type is None:
            continue
        # One broken scout must not hold back every scout after it on each hourly run.
        try:
            outcome = _sync_one(skill, scanner_type)
        except Exception:
            logger.exception(
                "replay_vision_scout_template_sync_failed", team_id=skill.team_id, skill_name=skill.skill_name
            )
            outcome = "failed"
        if outcome:
            counts[outcome] += 1
            if outcome in ("updated", "claimed"):
                logger.info(
                    f"replay_vision_scout_template_{outcome}", team_id=skill.team_id, skill_name=skill.skill_name
                )
    return TemplateSyncResult(**counts)
