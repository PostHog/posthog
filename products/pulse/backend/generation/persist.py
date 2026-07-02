from django.db import transaction

from products.pulse.backend.generation.schemas import BriefOut, OpportunityOut
from products.pulse.backend.models import Opportunity, ProductBrief
from products.pulse.backend.sources.base import SourceItem

_FINGERPRINT_MAX_LENGTH = Opportunity._meta.get_field("fingerprint").max_length or 512
_TITLE_MAX_LENGTH = Opportunity._meta.get_field("title").max_length or 400


def _fingerprint(kind: str, hint: str) -> str:
    return f"{kind}:{hint}"[:_FINGERPRINT_MAX_LENGTH]


def _fallback_evidence(evidence_refs: list[str]) -> list[dict]:
    # Only for refs the LLM emitted that resolve to no gathered item: parse the "type:ref" string.
    evidence = []
    for ref in evidence_refs:
        prefix, sep, rest = ref.partition(":")
        evidence.append({"type": prefix, "ref": rest if sep else prefix, "label": ""})
    return evidence


def _build_opportunity(brief: ProductBrief, opp: OpportunityOut, item: SourceItem | None) -> Opportunity:
    if item is not None:
        evidence = item.evidence
        baseline = item.numbers
        first_evidence = item.evidence[0] if item.evidence else None
        metric_ref = (
            {"insight_short_id": first_evidence["ref"]}
            if first_evidence and first_evidence.get("type") == "insight"
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
        fingerprint=_fingerprint(opp.kind, opp.fingerprint_hint),
    )


def persist_brief_output(*, brief: ProductBrief, out: BriefOut, items: list[SourceItem]) -> ProductBrief:
    team_opportunities = Opportunity.objects.for_team(brief.team_id)
    items_by_hint = {item.fingerprint_hint: item for item in items}
    with transaction.atomic():
        brief.sections = [s.model_dump() for s in out.sections]
        brief.status = ProductBrief.Status.READY if out.sections else ProductBrief.Status.QUIET
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
            new_opportunities.append(_build_opportunity(brief, opp, items_by_hint.get(opp.fingerprint_hint)))
        if new_opportunities:
            team_opportunities.bulk_create(new_opportunities)
    return brief
