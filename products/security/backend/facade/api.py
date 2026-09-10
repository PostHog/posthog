"""
Facade for security.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from ..logic import decisions
from ..logic.targets import Subject
from . import contracts


def decide(subject: contracts.SubjectInput) -> list[contracts.SurfaceDecision]:
    internal = Subject.for_account(
        email=subject.email,
        user_uuid=subject.user_uuid,
        organization_ids=frozenset(subject.organization_ids),
        team_ids=frozenset(subject.team_ids),
        ip=subject.ip,
    )
    return [
        contracts.SurfaceDecision(
            surface=decision.surface,
            blocked=decision.blocked,
            rule_id=decision.deciding_rule.id if decision.deciding_rule else None,
        )
        for decision in decisions.decide(internal)
    ]
