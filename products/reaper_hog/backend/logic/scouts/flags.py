from datetime import datetime

from products.feature_flags.backend.facade.api import FlagSummary, list_flag_summaries
from products.reaper_hog.backend.facade.enums import NAMED_SCOPES, SCOPE_ALL, SCOPE_FLAGS, RootKind, ScoutName
from products.reaper_hog.backend.logic.artefacts import EvidenceValue, Hit
from products.reaper_hog.backend.logic.constants import FLAG_DISABLED_DAYS, FLAG_FULL_ROLLOUT_DAYS, FLAG_UNCALLED_DAYS
from products.reaper_hog.backend.logic.repo import ReferenceCount
from products.reaper_hog.backend.logic.scouts.base import ScoutContext, days_between, flag_patterns


class FlagsScout:
    name = ScoutName.FLAGS

    def applies_to(self, scope: str) -> bool:
        return scope in (SCOPE_FLAGS, SCOPE_ALL) or scope not in NAMED_SCOPES

    def run(self, context: ScoutContext) -> list[Hit]:
        summaries = {summary.key: summary for summary in list_flag_summaries(context.team_id)}
        constant_by_key = {key: constant for constant, key in context.repo.frontend_flag_keys().items()}
        keys = sorted(set(summaries) | set(constant_by_key))
        references = context.repo.references_many({key: flag_patterns(key, constant_by_key.get(key)) for key in keys})
        hits: list[Hit] = []
        for key in keys:
            reference = references[key]
            if not reference.files or not context.in_scope(reference.files):
                continue
            hit = classify_flag(key, summaries.get(key), reference, context.now)
            if hit is not None:
                hits.append(hit)
        return hits


def classify_flag(key: str, summary: FlagSummary | None, reference: ReferenceCount, now: datetime) -> Hit | None:
    if summary is None:
        return _hit(key, reference, decisive=True, summary="No flag row on this project; every check evaluates false")
    evidence = _evidence(summary, reference)
    if summary.deleted:
        return _hit(
            key, reference, decisive=True, summary="Flag is deleted; every check evaluates false", evidence=evidence
        )
    if summary.archived:
        return _hit(
            key, reference, decisive=True, summary="Flag is archived; every check evaluates false", evidence=evidence
        )
    if not summary.active:
        since = summary.updated_at or summary.created_at
        days = days_between(now, since)
        if days >= FLAG_DISABLED_DAYS:
            return _hit(key, reference, summary=f"Flag disabled for at least {days} days", evidence=evidence)
        return None
    if summary.last_called_at is not None:
        days = days_between(now, summary.last_called_at)
        if days >= FLAG_UNCALLED_DAYS:
            return _hit(key, reference, summary=f"Flag not evaluated in {days} days", evidence=evidence)
    elif days_between(now, summary.created_at) >= FLAG_UNCALLED_DAYS:
        days = days_between(now, summary.created_at)
        return _hit(key, reference, summary=f"Flag never evaluated since creation {days} days ago", evidence=evidence)
    if summary.effectively_full_rollout and days_between(now, summary.created_at) >= FLAG_FULL_ROLLOUT_DAYS:
        keep = (
            f'variant "{summary.fully_rolled_out_variant}"' if summary.fully_rolled_out_variant else "the enabled path"
        )
        return _hit(
            key, reference, summary=f"Flag at 100% rollout; remove the check and keep {keep}", evidence=evidence
        )
    return None


def _hit(
    key: str,
    reference: ReferenceCount,
    *,
    summary: str,
    decisive: bool = False,
    evidence: dict[str, EvidenceValue] | None = None,
) -> Hit:
    return Hit(
        scout=ScoutName.FLAGS,
        root_kind=RootKind.FLAG,
        root=key,
        files=list(reference.files),
        reference_count=reference.total,
        decisive=decisive,
        summary=summary,
        evidence={
            **(evidence or {}),
            "code_files": len(reference.code_files),
            "test_files": len(reference.files) - len(reference.code_files),
            "references": reference.total,
        },
    )


def _evidence(summary: FlagSummary, reference: ReferenceCount) -> dict[str, EvidenceValue]:
    return {
        "flag_id": summary.id,
        "status": summary.status,
        "status_reason": summary.status_reason,
        "active": summary.active,
        "deleted": summary.deleted,
        "archived": summary.archived,
        "created_at": summary.created_at.isoformat(),
        "updated_at": summary.updated_at.isoformat() if summary.updated_at else None,
        "last_called_at": summary.last_called_at.isoformat() if summary.last_called_at else None,
        "max_rollout_percentage": summary.max_rollout_percentage,
        "fully_rolled_out_variant": summary.fully_rolled_out_variant,
        "variants": ", ".join(summary.variant_keys),
    }
