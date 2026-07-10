import hashlib

from django.db import transaction

import structlog

from products.pulse.backend.generation.schemas import BriefOut, OpportunityOut
from products.pulse.backend.models import Opportunity, ProductBrief
from products.pulse.backend.sources.base import EvidenceRef, EvidenceType, SourceItem, build_evidence_index

logger = structlog.get_logger(__name__)

_FINGERPRINT_MAX_LENGTH = Opportunity._meta.get_field("fingerprint").max_length or 512
_TITLE_MAX_LENGTH = Opportunity._meta.get_field("title").max_length or 400


def _fingerprint(kind: str, hint: str) -> str:
    # Hash the hint (not raw) so an unbounded hint can't overflow the column or collide with the
    # kind prefix; the kind prefix keeps fingerprints of different kinds distinct.
    digest = hashlib.sha256(hint.encode()).hexdigest()[:32]
    return f"{kind}:{digest}"[:_FINGERPRINT_MAX_LENGTH]


def _resolve_citations(citation_ids: list[str], evidence_index: dict[str, EvidenceRef]) -> list[EvidenceRef]:
    resolved: list[EvidenceRef] = []
    for citation_id in citation_ids:
        evidence = evidence_index.get(citation_id)
        if evidence is None:
            # The model cited an id we never rendered — drop it rather than fabricate a ref.
            logger.warning("pulse_persist_unknown_citation_id", citation_id=citation_id)
            continue
        resolved.append(evidence)
    return resolved


def _build_opportunity(
    brief: ProductBrief,
    opp: OpportunityOut,
    item: SourceItem | None,
    evidence_index: dict[str, EvidenceRef],
) -> Opportunity:
    evidence = _resolve_citations(opp.evidence_refs, evidence_index)
    baseline = item.metrics if item is not None else None
    first_insight = next((e for e in evidence if e["type"] == EvidenceType.INSIGHT), None)
    metric_ref = {"insight_short_id": first_insight["ref"]} if first_insight else None
    return Opportunity(
        team_id=brief.team_id,
        first_seen_brief=brief,
        kind=opp.kind,
        title=opp.title[:_TITLE_MAX_LENGTH],
        summary=opp.summary,
        suggested_action=opp.suggested_action,
        evidence=evidence,
        metric_ref=metric_ref,
        baseline=baseline,
        fingerprint=_fingerprint(opp.kind, opp.fingerprint_hint),
    )


def persist_brief_output(*, brief: ProductBrief, out: BriefOut, items: list[SourceItem]) -> ProductBrief:
    team_opportunities = Opportunity.objects.for_team(brief.team_id)
    items_by_hint = {item.fingerprint_hint: item for item in items}
    # Same index the render side built, so the ids the model cited resolve back to the same refs.
    evidence_index = build_evidence_index(items)
    with transaction.atomic():
        brief.sections = [s.model_dump() for s in out.sections]
        # A brief with only opportunities still has something to say — QUIET means nothing survived the gate.
        has_content = bool(out.sections or out.opportunities)
        brief.status = ProductBrief.Status.READY if has_content else ProductBrief.Status.QUIET
        brief.sources_used = sorted({item.source for item in items})
        brief.save(update_fields=["sections", "status", "sources_used", "updated_at"])
        seen = set(
            team_opportunities.filter(
                fingerprint__in=[_fingerprint(o.kind, o.fingerprint_hint) for o in out.opportunities],
            ).values_list("fingerprint", flat=True)
        )
        new_opportunities: list[Opportunity] = []
        for opp in out.opportunities:
            fingerprint = _fingerprint(opp.kind, opp.fingerprint_hint)
            if fingerprint in seen:
                continue  # open dupes AND dismissed fingerprints both suppress re-creation
            seen.add(fingerprint)
            new_opportunities.append(
                _build_opportunity(brief, opp, items_by_hint.get(opp.fingerprint_hint), evidence_index)
            )
        if new_opportunities:
            # ignore_conflicts: the (team, fingerprint) unique constraint absorbs concurrent-persist races.
            team_opportunities.bulk_create(new_opportunities, ignore_conflicts=True)
    return brief
