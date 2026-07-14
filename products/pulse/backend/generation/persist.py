import time
import uuid
import hashlib
import dataclasses

from django.db import transaction
from django.db.models import QuerySet

import structlog

from products.alerts.backend.models import AlertConfiguration
from products.annotations.backend.models.annotation import Annotation
from products.dashboards.backend.models.dashboard import Dashboard
from products.experiments.backend.models.experiment import Experiment
from products.exports.backend.models.subscription import Subscription
from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.generation.accountability import MAX_STATUS_LINES, OpportunityStatusLine
from products.pulse.backend.generation.goal import GoalStatus
from products.pulse.backend.generation.schemas import BriefOut, BriefSectionOut, OpportunityOut
from products.pulse.backend.models import Opportunity, ProductBrief, ResourceLink, build_action
from products.pulse.backend.sources.anchored_insights import (
    InsightResultsCache,
    resolve_metric_insight,
    series_daily_values,
    split_score_windows,
)
from products.pulse.backend.sources.base import EvidenceRef, EvidenceType, SourceItem, build_evidence_index

logger = structlog.get_logger(__name__)

# Cumulative wall-clock ceiling on proposal promotions, mirroring accountability's _RESCORE_BUDGET_SECONDS:
# promotions run after the LLM call inside the same fixed-length activity, so a burst of slow (but not
# timing-out) insight reads must not push the activity past its timeout and fail the brief.
_PROMOTION_BUDGET_SECONDS = 45

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


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


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


def _section_dict(section: BriefSectionOut, evidence_index: dict[str, EvidenceRef]) -> dict:
    # Resolve the LLM's opaque citation ids into structured refs at persist time, while the index is
    # in scope, so the API ships each section's citations as {type, ref, label, url} the client renders.
    return {
        "kind": section.kind,
        "title": section.title,
        "markdown": section.markdown,
        "citations": [ref.citation for ref in _resolve_citations(section.citations, evidence_index)],
        "confidence": section.confidence,
    }


def _validated_proposal(brief: ProductBrief, opp: OpportunityOut, item: SourceItem | None) -> dict | None:
    """The stored proposal JSON, or None when the opportunity carries no valid proposal.

    Deterministic guard, mirroring synthesize's goalless zeroing: the prompt allows a proposed
    experiment only on goal-relevant opportunities, but the model may not comply — persist is
    where non-compliance is dropped instead of stored.
    """
    if not opp.goal_relevant or opp.proposed_experiment is None:
        return None
    short_id = opp.proposed_experiment.target_metric_insight_short_id
    if item is not None:
        # The prompt's never-invent rule, code-enforced: the target must be among the resolved
        # item's (server-gathered) insight refs.
        valid = short_id in {e.ref for e in item.evidence if e.is_insight}
    else:
        # No item resolved, so the cited refs are LLM-authored — validating against them would be
        # circular. Resolving the insight (team-scoped, deleted excluded) is the server-authoritative
        # check instead.
        valid = resolve_metric_insight(brief.team, short_id) is not None
    return {
        "hypothesis": opp.proposed_experiment.hypothesis,
        "flag_key_suggestion": opp.proposed_experiment.flag_key_suggestion,
        # Nested to match the Opportunity.metric_ref convention for insight refs.
        "target_metric": {"insight_short_id": short_id} if valid else None,
        "variant_sketch": opp.proposed_experiment.variant_sketch,
    }


def _promoted_metric(
    brief: ProductBrief,
    proposed_experiment: dict,
    results_cache: InsightResultsCache,
    period_days: int,
) -> tuple[dict, dict] | None:
    """Close the suggest→act→measure loop for a proposal-carrying opportunity that resolved no
    metric of its own: promote the proposal's (already membership-validated) target metric into
    the `metric_ref`/`baseline` pair accountability re-scores, snapshotting the current window
    as the baseline. All-or-nothing: without a readable snapshot there is nothing to measure
    against, so neither field is set."""
    target = proposed_experiment.get("target_metric")
    if not target:
        return None
    short_id = target["insight_short_id"]
    if results_cache.attempts >= MAX_STATUS_LINES:
        # The shared per-run execution budget is spent — mirror accountability's gate. Logged so
        # the resulting metric_ref-less proposal (which re-scoring skips) is queryable, not silent.
        logger.info(
            "pulse_proposal_promotion_budget_exhausted",
            team_id=brief.team_id,
            brief_id=str(brief.id),
            insight_short_id=short_id,
        )
        return None
    try:
        # The insight resolve shares the try so a DB failure skips this one promotion rather than
        # aborting the whole brief persist. Bounded: results_for is memoized per run (the goal
        # metric is typically already cached), so a promotion costs at most one insight run.
        insight = resolve_metric_insight(brief.team, short_id)
        if insight is None:
            logger.info(
                "pulse_proposal_insight_missing",
                team_id=brief.team_id,
                brief_id=str(brief.id),
                insight_short_id=short_id,
            )
            return None
        results = results_cache.results_for(insight)
    except Exception:
        logger.warning(
            "pulse_proposal_metric_snapshot_failed",
            team_id=brief.team_id,
            brief_id=str(brief.id),
            insight_short_id=short_id,
            exc_info=True,
        )
        return None
    values = series_daily_values(results[0], period_days) if results else None
    windows = split_score_windows(values) if values is not None else None
    if windows is None:
        # Info log on the unreadable branch (mirrors accountability's pulse_accountability_metric
        # _unreadable): a non-trends shape or too-sparse series must be queryable, not just an
        # absent metric_ref an operator can't distinguish from a budget or resolve miss.
        logger.info(
            "pulse_proposal_metric_unreadable",
            team_id=brief.team_id,
            brief_id=str(brief.id),
            insight_short_id=short_id,
        )
        return None
    # The minimal shape accountability's usability gate requires — the same snapshot semantics
    # as anchored-insights movement numbers (current window total over period_days).
    return dict(target), {"current_total": float(sum(windows[1])), "period_days": period_days}


def _build_opportunity(
    brief: ProductBrief,
    opp: OpportunityOut,
    baseline: dict | None,
    metric_ref: dict | None,
    proposed_experiment: dict | None,
) -> Opportunity:
    """Pure construction from already-resolved values — no insight I/O — so promotion's side
    effect stays in persist_brief_output's loop, not hidden behind a construction call."""
    return Opportunity(
        team_id=brief.team_id,
        first_seen_brief=brief,
        kind=opp.kind,
        title=opp.title[:_TITLE_MAX_LENGTH],
        summary=opp.summary,
        action=build_action(opp.suggested_action),
        metric_ref=metric_ref,
        baseline=baseline,
        goal_relevant=opp.goal_relevant,
        proposed_experiment=proposed_experiment,
        fingerprint=_fingerprint(opp.kind, opp.fingerprint_hint),
    )


_LinkTarget = Insight | Dashboard | Annotation | Experiment | AlertConfiguration | Subscription


def _resolve_link_fks(team_id: int, evidence: list[EvidenceRef]) -> dict[tuple[EvidenceType, str], _LinkTarget]:
    """Batch-resolve cited refs, keyed by EvidenceRef.key, to the model instances the ResourceLink
    FKs point at. A ref that resolves to nothing is still linked (cached columns only)."""
    by_type: dict[EvidenceType, set[str]] = {}
    for ref in evidence:
        by_type.setdefault(ref.type, set()).add(ref.ref)

    resolved: dict[tuple[EvidenceType, str], _LinkTarget] = {}
    insight_refs = by_type.get(EvidenceType.INSIGHT)
    if insight_refs:
        for insight in Insight.objects.filter(team_id=team_id, short_id__in=insight_refs):
            resolved[(EvidenceType.INSIGHT, insight.short_id)] = insight
    alert_refs = by_type.get(EvidenceType.ALERT)
    if alert_refs:
        # AlertConfiguration has a UUID primary key; a non-UUID ref would raise on the query, so
        # filter it out (mirrors the non-numeric guard below) and it stays an FK-less link.
        valid_uuids = {r for r in alert_refs if _is_uuid(r)}
        if invalid := alert_refs - valid_uuids:
            logger.warning("pulse_persist_non_uuid_ref", evidence_type=EvidenceType.ALERT, refs=sorted(invalid))
        for alert in AlertConfiguration.objects.filter(team_id=team_id, id__in=valid_uuids):
            resolved[(EvidenceType.ALERT, str(alert.id))] = alert
    for evidence_type, model in (
        (EvidenceType.DASHBOARD, Dashboard),
        (EvidenceType.ANNOTATION, Annotation),
        (EvidenceType.EXPERIMENT, Experiment),
        (EvidenceType.SUBSCRIPTION, Subscription),
    ):
        refs = by_type.get(evidence_type)
        if not refs:
            continue
        numeric_ids = [int(r) for r in refs if r.isdigit()]
        if non_numeric := refs - {str(i) for i in numeric_ids}:
            # These models have integer PKs; a non-numeric ref can't resolve (its link stays FK-less).
            logger.warning("pulse_persist_non_numeric_ref", evidence_type=evidence_type, refs=sorted(non_numeric))
        for obj in model.objects.filter(team_id=team_id, id__in=numeric_ids):
            resolved[(evidence_type, str(obj.id))] = obj
    return resolved


def _build_links(
    opportunity: Opportunity,
    evidence: list[EvidenceRef],
    resolved_fks: dict[tuple[EvidenceType, str], _LinkTarget],
) -> list[ResourceLink]:
    links: list[ResourceLink] = []
    for ref in evidence:
        link = ResourceLink(
            team_id=opportunity.team_id,
            opportunity=opportunity,
            resource_type=ref.resource_type,
            ref=ref.ref[:_REF_MAX_LENGTH],
            label=ref.label[:_LABEL_MAX_LENGTH],
            url=ref.url[:_URL_MAX_LENGTH],
        )
        if ref.fk_field is not None:
            setattr(link, ref.fk_field, resolved_fks.get(ref.key))
        links.append(link)
    return links


def _existing_fingerprints(team_opportunities: QuerySet[Opportunity], fingerprints: list[str]) -> set[str]:
    return set(team_opportunities.filter(fingerprint__in=fingerprints).values_list("fingerprint", flat=True))


def persist_brief_output(
    *,
    brief: ProductBrief,
    out: BriefOut,
    items: list[SourceItem],
    status_lines: list[OpportunityStatusLine] | None = None,
    goal_status: GoalStatus | None = None,
    period_days: int | None = None,
    results_cache: InsightResultsCache | None = None,
) -> ProductBrief:
    team_opportunities = Opportunity.objects.for_team(brief.team_id)
    items_by_hint = {item.fingerprint_hint: item for item in items}
    # Same index the render side built, so the ids the model cited resolve back to the same refs.
    evidence_index = build_evidence_index(items)
    results_cache = results_cache or InsightResultsCache(brief.team)
    # The window a promoted metric is snapshotted over: the caller's resolved lookback, falling
    # back to the brief's period spec (default 7) for callers that don't thread one through.
    window_days = period_days if period_days is not None else int(brief.period.get("days", 7))

    # Rows are built before the write transaction on purpose: a target-metric promotion may execute
    # an insight (a slow read), which must not stretch the transaction. The dedup pre-check needs no
    # transactional protection either — the (team, fingerprint) unique constraint plus ignore_conflicts
    # below is the real race guard.
    seen = _existing_fingerprints(
        team_opportunities, [_fingerprint(o.kind, o.fingerprint_hint) for o in out.opportunities]
    )
    new_opportunities: list[Opportunity] = []
    links_by_opportunity: list[tuple[Opportunity, list[EvidenceRef]]] = []
    promotion_started = time.monotonic()
    for opp in out.opportunities:
        fingerprint = _fingerprint(opp.kind, opp.fingerprint_hint)
        if fingerprint in seen:
            continue  # open dupes AND dismissed fingerprints both suppress re-creation
        seen.add(fingerprint)
        item = items_by_hint.get(opp.fingerprint_hint)
        evidence = _resolve_citations(opp.evidence_refs, evidence_index)
        baseline = item.metrics if item is not None else None
        first_insight = next((e for e in evidence if e.is_insight), None)
        metric_ref = first_insight.metric_ref if first_insight else None
        proposed_experiment = _validated_proposal(brief, opp, item)
        # Close the suggest→act→measure loop: a proposal-carrying opportunity that resolved no metric
        # of its own promotes its validated target metric, snapshotting the current window as baseline.
        if proposed_experiment is not None and metric_ref is None:
            if time.monotonic() - promotion_started > _PROMOTION_BUDGET_SECONDS:
                # Budget spent — keep the proposal (target_metric intact) but skip the snapshot, so a
                # slow run degrades to a metric_ref-less proposal (queryable) instead of overrunning
                # the activity timeout. Mirrors accountability's pulse_accountability_budget_exceeded.
                logger.warning(
                    "pulse_proposal_promotion_budget_exceeded", team_id=brief.team_id, brief_id=str(brief.id)
                )
            else:
                promoted = _promoted_metric(brief, proposed_experiment, results_cache, window_days)
                if promoted is not None:
                    metric_ref, baseline = promoted
        opportunity = _build_opportunity(brief, opp, baseline, metric_ref, proposed_experiment)
        new_opportunities.append(opportunity)
        links_by_opportunity.append((opportunity, evidence))

    with transaction.atomic():
        brief.sections = [_section_dict(s, evidence_index) for s in out.sections]
        # Deterministic, code-computed then-vs-now re-scores — persisted alongside the LLM output
        # so the frontend renders metric movement without round-tripping it through the model.
        brief.accountability = [dataclasses.asdict(line) for line in (status_lines or [])]
        # A brief with only opportunities still has something to say — QUIET means nothing survived the gate.
        has_content = bool(out.sections or out.opportunities)
        brief.status = ProductBrief.Status.READY if has_content else ProductBrief.Status.QUIET
        brief.sources_used = sorted({item.source for item in items})
        # Freeze the goal figures the brief was framed with, so the UI shows the same snapshot
        # the synthesis prompt saw rather than a live re-read.
        brief.goal_status = dataclasses.asdict(goal_status) if goal_status is not None else None
        brief.save(update_fields=["sections", "accountability", "status", "sources_used", "goal_status", "updated_at"])
        if new_opportunities:
            # ignore_conflicts lets a concurrent persist that inserted the same (team, fingerprint)
            # between the dedup read above and here win the race without erroring.
            team_opportunities.bulk_create(new_opportunities, ignore_conflicts=True)
            # A lost (team, fingerprint) race skips our insert, yet our in-memory opportunity keeps
            # its id — linking against it would dangle the ResourceLink FK and abort the whole brief.
            # So re-read and link only the opportunities we actually inserted; the winner owns the rest.
            persisted_ids = dict(
                team_opportunities.filter(fingerprint__in=[o.fingerprint for o in new_opportunities]).values_list(
                    "fingerprint", "id"
                )
            )
            owned = [
                (opportunity, evidence)
                for opportunity, evidence in links_by_opportunity
                if persisted_ids.get(opportunity.fingerprint) == opportunity.id
            ]
            if owned:
                all_evidence = [ref for _, evidence in owned for ref in evidence]
                resolved_fks = _resolve_link_fks(brief.team_id, all_evidence)
                links = [
                    link
                    for opportunity, evidence in owned
                    for link in _build_links(opportunity, evidence, resolved_fks)
                ]
                if links:
                    ResourceLink.objects.for_team(brief.team_id).bulk_create(links, ignore_conflicts=True)
    return brief
