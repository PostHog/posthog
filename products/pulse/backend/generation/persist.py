from django.db import transaction

from products.pulse.backend.generation.schemas import BriefOut, OpportunityOut
from products.pulse.backend.models import Opportunity, ProductBrief
from products.pulse.backend.sources.base import EvidenceRef, SourceItem

_FINGERPRINT_MAX_LENGTH = Opportunity._meta.get_field("fingerprint").max_length or 512
_TITLE_MAX_LENGTH = Opportunity._meta.get_field("title").max_length or 400


def opportunity_fingerprint(kind: str, hint: str) -> str:
    return f"{kind}:{hint}"[:_FINGERPRINT_MAX_LENGTH]


def _fallback_evidence(evidence_refs: list[str]) -> list[EvidenceRef]:
    # Only for refs the LLM emitted that resolve to no gathered item: parse the "type:ref" string.
    evidence: list[EvidenceRef] = []
    for ref in evidence_refs:
        prefix, sep, rest = ref.partition(":")
        evidence.append(EvidenceRef(type=prefix, ref=rest if sep else prefix, label=""))
    return evidence


def _build_opportunity(brief: ProductBrief, opp: OpportunityOut, item: SourceItem | None) -> Opportunity:
    if item is not None:
        evidence = item.evidence
        baseline = item.numbers
        first_evidence = item.evidence[0] if item.evidence else None
        metric_ref = (
            {"insight_short_id": first_evidence["ref"]}
            if first_evidence and first_evidence["type"] == "insight"
            else None
        )
    else:
        evidence = _fallback_evidence(opp.evidence_refs)
        baseline = None
        metric_ref = None
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
        goal_relevant=opp.goal_relevant,
        fingerprint=opportunity_fingerprint(opp.kind, opp.fingerprint_hint),
    )


def persist_brief_output(*, brief: ProductBrief, out: BriefOut, items: list[SourceItem]) -> list[Opportunity]:
    """Persist the brief output in place and return the newly created (non-deduped) opportunities."""
    team_opportunities = Opportunity.objects.for_team(brief.team_id)
    items_by_hint = {item.fingerprint_hint: item for item in items}
    with transaction.atomic():
        brief.sections = [s.model_dump() for s in out.sections]
        # A brief with only opportunities still has something to say — QUIET means nothing survived the gate.
        has_content = bool(out.sections or out.opportunities)
        brief.status = ProductBrief.Status.READY if has_content else ProductBrief.Status.QUIET
        brief.sources_used = sorted({item.source for item in items})
        brief.save(update_fields=["sections", "status", "sources_used", "updated_at"])
        seen = set(
            team_opportunities.filter(
                fingerprint__in=[opportunity_fingerprint(o.kind, o.fingerprint_hint) for o in out.opportunities],
            ).values_list("fingerprint", flat=True)
        )
        new_opportunities: list[Opportunity] = []
        for opp in out.opportunities:
            fingerprint = opportunity_fingerprint(opp.kind, opp.fingerprint_hint)
            if fingerprint in seen:
                continue  # an existing fingerprint in ANY status suppresses re-creation (reopen doesn't resurrect)
            seen.add(fingerprint)
            new_opportunities.append(_build_opportunity(brief, opp, items_by_hint.get(opp.fingerprint_hint)))
        if not new_opportunities:
            return []
        # ignore_conflicts: the (team, fingerprint) unique constraint absorbs concurrent-persist races.
        team_opportunities.bulk_create(new_opportunities, ignore_conflicts=True)
        # Re-read the persisted rows: a row that lost the unique-constraint race to a concurrent
        # persist must surface with its persisted id, not this call's never-inserted UUID.
        return list(team_opportunities.filter(fingerprint__in=[o.fingerprint for o in new_opportunities]))
