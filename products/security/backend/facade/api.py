"""
Facade for security.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from ..logic.accounts import email_for_user
from ..logic.decisions import deciding_rule
from ..logic.snapshot import current_snapshot
from ..logic.subjects import normalize_subject
from ..metrics import DECISION_ERRORS_COUNTER, WOULD_BLOCK_COUNTER
from . import contracts
from .enums import Outcome, Surface

logger = structlog.get_logger(__name__)

_OUTCOME_FOR_MATCH = {Surface.EMAIL_CODE: Outcome.EXEMPT}


def decide(subject: contracts.SubjectInput, surface: Surface) -> contracts.Decision:
    # Without the email, a posthog.com user named only by ID would skip the protection.
    email = subject.email or (email_for_user(subject.user_uuid) if subject.user_uuid else None)
    normalized = normalize_subject(
        email=email,
        user_uuid=subject.user_uuid,
        organization_ids=subject.organization_ids,
        ip=subject.ip,
    )
    rule = deciding_rule(current_snapshot().index, normalized, surface, datetime.now(UTC))
    if rule is None:
        return contracts.Decision(surface=surface, outcome=Outcome.ALLOW)
    return contracts.Decision(
        surface=surface,
        outcome=_OUTCOME_FOR_MATCH.get(surface, Outcome.BLOCK),
        rule_id=rule.id,
        target_type=rule.target_type,
    )


def is_email_code_exempt(email: str) -> bool:
    """Whether a rule lets this address skip the emailed login code. Any failure keeps the code."""
    try:
        return decide(contracts.SubjectInput(email=email), Surface.EMAIL_CODE).outcome == Outcome.EXEMPT
    except Exception:
        logger.exception("security_email_code_exemption_check_failed")
        DECISION_ERRORS_COUNTER.labels(call_site="email_code").inc()
        return False


def shadow_check(subject: contracts.SubjectInput, surface: Surface, *, call_site: str) -> None:
    """Records what a block rule would do here, and changes nothing. Never raises."""
    try:
        decision = decide(subject, surface)
        if decision.outcome != Outcome.BLOCK:
            return
        WOULD_BLOCK_COUNTER.labels(
            surface=surface.value, call_site=call_site, target_type=decision.target_type or ""
        ).inc()
        logger.info(
            "security_access_would_block",
            surface=surface.value,
            call_site=call_site,
            rule_id=decision.rule_id,
            target_type=decision.target_type,
            user_uuid=subject.user_uuid,
        )
    except Exception:
        logger.exception("security_access_shadow_check_failed", call_site=call_site)
        DECISION_ERRORS_COUNTER.labels(call_site=call_site).inc()
