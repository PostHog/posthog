"""Keeps scanner scouts created from a template on the template's latest text.

A scout is claimed when its text is exactly what a template rendered. Right before each run, a claimed scout
whose text still matches the hash recorded at its last write gets the current template text as a new skill
version. A scout someone has edited no longer matches, so it keeps their text.
"""

import re
import uuid
import hashlib

import structlog

from posthog.models import Team

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
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


def _scanner_type(team_id: int, scanner_id: str) -> str | None:
    """The scanner's type, when it sits on the scout's team or one of that team's environments."""
    try:
        scanner_uuid = uuid.UUID(scanner_id)
    except ValueError:
        return None
    team_ids = [team_id, *Team.objects.filter(parent_team_id=team_id).values_list("id", flat=True)]
    # Scoped to the scout's team and its environments, which the single-team rule can't express.
    # nosemgrep: idor-lookup-without-team
    scanners = ReplayScanner.objects.filter(id=scanner_uuid, team_id__in=team_ids)
    return scanners.values_list("scanner_type", flat=True).first()


def _refresh(skill: signals_facade.SourceScoutSkill, scanner_type: str) -> str | None:
    """Bring one scout up to date, returning what happened to it, or None when nothing did."""
    scanner_id = skill.source_id.lower()
    key = _key_from_record(skill.template)
    template_hash = skill.template_hash
    if key is None:
        # A scout created before claiming existed: claim it when its text is a template's, untouched.
        key = template_key_from_skill_name(skill.skill_name)
        if key not in SYNCED_TEMPLATE_KEYS or not (
            skill.body == render_template_body(key, scanner_id, scanner_type)
            or _is_legacy_template_body(key, skill.body, scanner_id)
        ):
            return None
        if not _claim(team_id=skill.team_id, skill_name=skill.skill_name, version=skill.version, key=key):
            return None
        template_hash = signals_facade.source_scout_body_hash(skill.body)
    if signals_facade.source_scout_body_hash(skill.body) != template_hash:
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


def refresh_template_scout(team_id: int, skill_name: str, scanner_id: str) -> None:
    """Signals calls this right before a scanner scout runs, so the run reads the latest template text."""
    scanner_type = _scanner_type(team_id, scanner_id)
    skill = signals_facade.source_scout_skill(team_id, skill_name) if scanner_type else None
    if skill is None or scanner_type is None:
        return
    outcome = _refresh(skill, scanner_type)
    if outcome == "updated":
        logger.info("replay_vision_scout_template_updated", team_id=team_id, skill_name=skill_name)
