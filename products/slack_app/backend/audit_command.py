"""
Staff-initiated read-only audit runs against customer projects.

V0 entry point is a Django management command (`./manage.py ph_audit`); a
Slack slash-command surface is a planned follow-up that will reuse the
helpers in this module.

What runs today:
- `dispatch_audit_run` validates the skill, mints a TTL-bound, project-scoped,
  read-only Personal API key, writes an `external_audit_started` entry to the
  customer's activity log, and logs the dispatch.
- The actual agent invocation (Temporal workflow that runs the skill bundle
  against the project using the ephemeral key) is intentionally a follow-up —
  see the TODO in `dispatch_audit_run`.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

import structlog

from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value, mask_key_value
from posthog.scopes import downgrade_scopes_to_read_only

logger = structlog.get_logger(__name__)

# Ephemeral PAT TTL for an audit run. One hour is well over the time any
# `auditing-*` / `diagnosing-*` skill takes to complete in practice, and
# short enough that an accidentally leaked key has a small window.
AUDIT_KEY_TTL = timedelta(hours=1)
AUDIT_KEY_LABEL_PREFIX = "audit"

# V0 read-only audit skills. Every entry here must be a non-mutating
# investigation/audit skill — adding write-capable skills here is a security
# decision that needs a separate review.
AUDIT_SKILLS: frozenset[str] = frozenset(
    {
        "auditing-experiments-flags",
        "auditing-warehouse-data-health",
        "cleaning-up-stale-feature-flags",  # the *finding* half; cleanup itself is a separate flow
        "diagnosing-failed-warehouse-syncs",
        "diagnosing-missing-recordings",
        "diagnosing-sdk-health",
        "diagnosing-stacktrace-symbolication",
    }
)


class AuditCommandError(Exception):
    """Raised when audit arguments fail validation."""


@dataclass(frozen=True)
class AuditRunResult:
    api_key: PersonalAPIKey
    raw_token: str


def validate_skill(skill: str) -> str:
    if skill not in AUDIT_SKILLS:
        raise AuditCommandError(
            f"`{skill}` isn't an allowed audit skill. Pick one of: {', '.join(sorted(AUDIT_SKILLS))}."
        )
    return skill


def log_audit_run_started(*, team: Team, staff_user: User, skill: str) -> None:
    log_activity(
        organization_id=team.organization_id,
        team_id=team.id,
        user=staff_user,
        item_id=team.id,
        scope="Team",
        activity="external_audit_started",
        detail=Detail(name=team.name, type=skill),
        was_impersonated=False,
    )


def mint_ephemeral_audit_key(*, team: Team, staff_user: User, skill: str) -> tuple[PersonalAPIKey, str]:
    """Mint a TTL-bound, project-scoped, read-only personal API key for an
    audit run. Returns `(key_row, raw_token)` — `raw_token` is the only place
    the plaintext value exists and must be handed to the agent immediately;
    the database stores only the hash.

    Scopes are the explicit expansion of `*:read` (see
    `downgrade_scopes_to_read_only`) so the wildcard short-circuit in
    `posthog/permissions.py` doesn't grant write by accident.
    """
    raw_token = generate_random_token_personal()
    read_only_scopes = downgrade_scopes_to_read_only("*").split()
    # `PersonalAPIKey.label` is varchar(40); slice the formatted label to fit
    # even if a future allowlist entry has a long name. The full skill identifier
    # is preserved in the activity log entry's `Detail.type`.
    label = f"{AUDIT_KEY_LABEL_PREFIX}: {skill}"[:40]
    key = PersonalAPIKey.objects.create(
        user=staff_user,
        label=label,
        secure_value=hash_key_value(raw_token),
        mask_value=mask_key_value(raw_token),
        scopes=read_only_scopes,
        scoped_teams=[team.id],
        expires_at=timezone.now() + AUDIT_KEY_TTL,
    )
    return key, raw_token


def dispatch_audit_run(*, team: Team, staff_user: User, skill: str) -> AuditRunResult:
    """Validate input, mint a scoped read-only ephemeral key for the agent,
    write the activity log entry, then hand off.

    The actual agent dispatch (Temporal workflow that runs the skill bundle
    against the project using `raw_token`) is the remaining follow-up — at
    that point this helper just needs the raw token plumbed into the workflow
    inputs. Mint-and-log is safe to ship now because expired keys are rejected
    by both the DRF authenticator and the lookup helper.

    Raises `AuditCommandError` if `skill` isn't allowlisted or `staff_user`
    isn't flagged `is_staff`. Callers should treat this as the single
    authorization checkpoint for an audit run.
    """
    validate_skill(skill)
    if not staff_user.is_staff:
        raise AuditCommandError("Audit runs are restricted to staff users.")

    log_audit_run_started(team=team, staff_user=staff_user, skill=skill)
    key, raw_token = mint_ephemeral_audit_key(team=team, staff_user=staff_user, skill=skill)
    logger.info(
        "audit_dispatch_minted_key",
        team_id=team.id,
        staff_user_id=staff_user.id,
        skill=skill,
        api_key_id=key.id,
        api_key_expires_at=key.expires_at.isoformat() if key.expires_at else None,
    )
    return AuditRunResult(api_key=key, raw_token=raw_token)
