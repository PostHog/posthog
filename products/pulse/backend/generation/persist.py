from django.db import transaction

from products.pulse.backend.generation.schemas import BriefOut
from products.pulse.backend.models import Opportunity, ProductBrief

FINGERPRINT_MAX_LENGTH = 512


def _fingerprint(kind: str, hint: str) -> str:
    return f"{kind}:{hint}"[:FINGERPRINT_MAX_LENGTH]


def persist_brief_output(*, brief: ProductBrief, out: BriefOut) -> ProductBrief:
    team_opportunities = Opportunity.objects.for_team(brief.team_id)
    with transaction.atomic():
        brief.sections = [s.model_dump() for s in out.sections]
        brief.status = ProductBrief.Status.READY if out.sections else ProductBrief.Status.QUIET
        brief.save(update_fields=["sections", "status", "updated_at"])
        existing = set(
            team_opportunities.filter(
                fingerprint__in=[_fingerprint(o.kind, o.fingerprint_hint) for o in out.opportunities],
            ).values_list("fingerprint", flat=True)
        )
        for opp in out.opportunities:
            fingerprint = _fingerprint(opp.kind, opp.fingerprint_hint)
            if fingerprint in existing:
                continue  # open dupes AND dismissed fingerprints both suppress re-creation
            team_opportunities.create(
                team_id=brief.team_id,
                first_seen_brief=brief,
                kind=opp.kind,
                title=opp.title[:400],
                summary=opp.summary,
                suggested_action=opp.suggested_action,
                evidence=[
                    {"type": r.split(":", 1)[0], "ref": r.split(":", 1)[-1], "label": ""} for r in opp.evidence_refs
                ],
                fingerprint=fingerprint,
            )
    return brief
