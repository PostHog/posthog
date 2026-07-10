import hashlib

from django.db import transaction

import structlog

from products.annotations.backend.models.annotation import Annotation
from products.dashboards.backend.models.dashboard import Dashboard
from products.experiments.backend.models.experiment import Experiment
from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.generation.schemas import BriefOut, OpportunityOut
from products.pulse.backend.models import Opportunity, ProductBrief, ResourceLink, ResourceType, build_action
from products.pulse.backend.sources.base import EvidenceRef, EvidenceType, SourceItem, build_evidence_index

logger = structlog.get_logger(__name__)

_FINGERPRINT_MAX_LENGTH = Opportunity._meta.get_field("fingerprint").max_length or 512
_TITLE_MAX_LENGTH = Opportunity._meta.get_field("title").max_length or 400
_REF_MAX_LENGTH = ResourceLink._meta.get_field("ref").max_length or 400
_LABEL_MAX_LENGTH = ResourceLink._meta.get_field("label").max_length or 400
_URL_MAX_LENGTH = ResourceLink._meta.get_field("url").max_length or 1000


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
    brief: ProductBrief, opp: OpportunityOut, item: SourceItem | None, evidence: list[EvidenceRef]
) -> Opportunity:
    baseline = item.metrics if item is not None else None
    first_insight = next((e for e in evidence if e["type"] == EvidenceType.INSIGHT), None)
    metric_ref = {"insight_short_id": first_insight["ref"]} if first_insight else None
    return Opportunity(
        team_id=brief.team_id,
        first_seen_brief=brief,
        kind=opp.kind,
        title=opp.title[:_TITLE_MAX_LENGTH],
        summary=opp.summary,
        action=build_action(opp.suggested_action),
        metric_ref=metric_ref,
        baseline=baseline,
        fingerprint=_fingerprint(opp.kind, opp.fingerprint_hint),
    )


def _resolve_link_fks(
    team_id: int, evidence: list[EvidenceRef]
) -> dict[str, Insight | Dashboard | Annotation | Experiment]:
    """Batch-resolve cited refs to the model instances the ResourceLink FKs point at, per team.

    Insights are looked up by short_id; dashboards/annotations/experiments by id. Events have no
    model. A ref that resolves to nothing is still linked (cached columns only) — the resource may
    have been deleted since the brief cited it.
    """
    by_type: dict[str, set[str]] = {}
    for ref in evidence:
        by_type.setdefault(ref["type"], set()).add(ref["ref"])

    resolved: dict[str, Insight | Dashboard | Annotation | Experiment] = {}
    insight_ids = by_type.get(EvidenceType.INSIGHT)
    if insight_ids:
        for insight in Insight.objects.filter(team_id=team_id, short_id__in=insight_ids):
            resolved[f"{EvidenceType.INSIGHT}:{insight.short_id}"] = insight
    for evidence_type, model in (
        (EvidenceType.DASHBOARD, Dashboard),
        (EvidenceType.ANNOTATION, Annotation),
        (EvidenceType.EXPERIMENT, Experiment),
    ):
        refs = by_type.get(evidence_type)
        if not refs:
            continue
        numeric_ids = [int(r) for r in refs if r.isdigit()]
        for obj in model.objects.filter(team_id=team_id, id__in=numeric_ids):
            resolved[f"{evidence_type}:{obj.id}"] = obj
    return resolved


# EvidenceType and ResourceType share the same members; each DB-modeled type has a matching FK field.
_FK_FIELD_BY_TYPE = {
    EvidenceType.INSIGHT: "insight",
    EvidenceType.DASHBOARD: "dashboard",
    EvidenceType.ANNOTATION: "annotation",
    EvidenceType.EXPERIMENT: "experiment",
}


def _build_links(
    opportunity: Opportunity,
    evidence: list[EvidenceRef],
    resolved_fks: dict[str, Insight | Dashboard | Annotation | Experiment],
) -> list[ResourceLink]:
    links: list[ResourceLink] = []
    for ref in evidence:
        # A ref whose type is not a known ResourceType is stored as an event (cached columns, no FK).
        resource_type = ref["type"] if ref["type"] in ResourceType.values else ResourceType.EVENT.value
        link = ResourceLink(
            team_id=opportunity.team_id,
            opportunity=opportunity,
            resource_type=resource_type,
            ref=ref["ref"][:_REF_MAX_LENGTH],
            label=ref["label"][:_LABEL_MAX_LENGTH],
            url=ref["url"][:_URL_MAX_LENGTH],
        )
        fk_field = _FK_FIELD_BY_TYPE.get(EvidenceType(resource_type))
        if fk_field is not None:
            setattr(link, fk_field, resolved_fks.get(f"{ref['type']}:{ref['ref']}"))
        links.append(link)
    return links


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
        links_by_opportunity: list[tuple[Opportunity, list[EvidenceRef]]] = []
        for opp in out.opportunities:
            fingerprint = _fingerprint(opp.kind, opp.fingerprint_hint)
            if fingerprint in seen:
                continue  # open dupes AND dismissed fingerprints both suppress re-creation
            seen.add(fingerprint)
            evidence = _resolve_citations(opp.evidence_refs, evidence_index)
            opportunity = _build_opportunity(brief, opp, items_by_hint.get(opp.fingerprint_hint), evidence)
            new_opportunities.append(opportunity)
            links_by_opportunity.append((opportunity, evidence))
        if new_opportunities:
            # ignore_conflicts: the (team, fingerprint) unique constraint absorbs concurrent-persist races.
            team_opportunities.bulk_create(new_opportunities, ignore_conflicts=True)
            all_evidence = [ref for _, evidence in links_by_opportunity for ref in evidence]
            resolved_fks = _resolve_link_fks(brief.team_id, all_evidence)
            links = [
                link
                for opportunity, evidence in links_by_opportunity
                for link in _build_links(opportunity, evidence, resolved_fks)
            ]
            if links:
                ResourceLink.objects.for_team(brief.team_id).bulk_create(links, ignore_conflicts=True)
    return brief
