import dataclasses

from django.db import transaction

import structlog

from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.generation.accountability import MAX_STATUS_LINES
from products.pulse.backend.generation.investigate import InvestigationFinding
from products.pulse.backend.generation.schemas import BriefOut, OpportunityOut
from products.pulse.backend.models import Opportunity, ProductBrief
from products.pulse.backend.sources.anchored_insights import (
    InsightResultsCache,
    resolve_metric_insight,
    series_daily_values,
    split_score_windows,
)
from products.pulse.backend.sources.base import EvidenceRef, SourceItem

logger = structlog.get_logger(__name__)

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


def _validated_proposal(
    brief: ProductBrief, opp: OpportunityOut, item: SourceItem | None, evidence: list[EvidenceRef]
) -> tuple[dict | None, Insight | None]:
    """The stored proposal JSON plus, on the fallback path, the already-resolved target insight
    (so promotion doesn't resolve it twice).

    Deterministic guard, mirroring synthesize's goalless zeroing: the prompt allows a proposed
    experiment only on goal-relevant opportunities, but the model may not comply — persist is
    where non-compliance is dropped instead of stored.
    """
    if not opp.goal_relevant or opp.proposed_experiment is None:
        return None, None
    short_id = opp.proposed_experiment.target_metric_insight_short_id
    target_insight: Insight | None = None
    if item is not None:
        # The prompt's never-invent rule, code-enforced: the target must be among the resolved
        # item's (server-gathered) insight refs.
        valid = short_id in {entry["ref"] for entry in evidence if entry["type"] == "insight"}
    else:
        # No item resolved, so the evidence refs are LLM-authored — validating against them
        # would be circular. Resolving the insight (team-scoped, deleted excluded) is the
        # server-authoritative check instead.
        target_insight = resolve_metric_insight(brief.team, short_id)
        valid = target_insight is not None
    return {
        "hypothesis": opp.proposed_experiment.hypothesis,
        "flag_key_suggestion": opp.proposed_experiment.flag_key_suggestion,
        # Nested to match the Opportunity.metric_ref convention for insight refs.
        "target_metric": {"insight_short_id": short_id} if valid else None,
        "variant_sketch": opp.proposed_experiment.variant_sketch,
    }, target_insight


def _promoted_metric(
    brief: ProductBrief,
    proposed_experiment: dict | None,
    results_cache: InsightResultsCache,
    target_insight: Insight | None,
) -> tuple[dict, dict] | None:
    """Close the suggest→act→measure loop for a proposal-carrying opportunity that resolved no
    metric of its own: promote the proposal's (already membership-validated) target metric into
    the `metric_ref`/`baseline` pair accountability re-scores, snapshotting the current window
    as the baseline. All-or-nothing: without a readable snapshot there is nothing to measure
    against, so neither field is set."""
    target = (proposed_experiment or {}).get("target_metric")
    if not target:
        return None
    if results_cache.attempts >= MAX_STATUS_LINES:
        return None  # the shared per-run execution budget is spent — mirror accountability's gate
    short_id = target["insight_short_id"]
    insight = target_insight or resolve_metric_insight(brief.team, short_id)
    if insight is None:
        return None
    try:
        # Bounded: memoized per run (the goal metric is typically already cached), so a
        # promotion costs at most one cached-execution-mode insight run.
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
    values = series_daily_values(results[0], brief.period_days) if results else None
    if values is None:
        return None
    windows = split_score_windows(values)
    if windows is None:
        return None
    # The minimal shape accountability's usability gate requires — the same snapshot semantics
    # as anchored-insights movement numbers (current window total over period_days).
    return dict(target), {"current_total": float(sum(windows[1])), "period_days": brief.period_days}


def _build_opportunity(
    brief: ProductBrief, opp: OpportunityOut, item: SourceItem | None, results_cache: InsightResultsCache
) -> Opportunity:
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
    proposed_experiment, target_insight = _validated_proposal(brief, opp, item, evidence)
    if proposed_experiment is not None and metric_ref is None:
        promoted = _promoted_metric(brief, proposed_experiment, results_cache, target_insight)
        if promoted is not None:
            metric_ref, baseline = promoted
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
        proposed_experiment=proposed_experiment,
        fingerprint=opportunity_fingerprint(opp.kind, opp.fingerprint_hint),
    )


def persist_brief_output(
    *,
    brief: ProductBrief,
    out: BriefOut,
    items: list[SourceItem],
    findings: list[InvestigationFinding],
    results_cache: InsightResultsCache | None = None,
) -> list[Opportunity]:
    """Persist the brief output in place and return the newly created (non-deduped) opportunities."""
    team_opportunities = Opportunity.objects.for_team(brief.team_id)
    items_by_hint = {item.fingerprint_hint: item for item in items}
    results_cache = results_cache or InsightResultsCache(brief.team)
    # Rows are built before the write transaction on purpose: a target-metric promotion may
    # execute an insight (a slow read), which must not stretch the transaction. The dedup
    # pre-check needs no transactional protection either — the (team, fingerprint) unique
    # constraint plus ignore_conflicts below is the real race guard.
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
        new_opportunities.append(_build_opportunity(brief, opp, items_by_hint.get(opp.fingerprint_hint), results_cache))
    with transaction.atomic():
        brief.sections = [s.model_dump() for s in out.sections]
        # Findings persist in citation order — query:<n> refs in section citations are
        # 1-based indexes into this list.
        brief.investigation = [dataclasses.asdict(finding) for finding in findings]
        # A brief with only opportunities still has something to say — QUIET means nothing survived the gate.
        has_content = bool(out.sections or out.opportunities)
        brief.status = ProductBrief.Status.READY if has_content else ProductBrief.Status.QUIET
        brief.sources_used = sorted({item.source for item in items})
        brief.save(update_fields=["sections", "investigation", "status", "sources_used", "updated_at"])
        if not new_opportunities:
            return []
        # ignore_conflicts: the (team, fingerprint) unique constraint absorbs concurrent-persist races.
        team_opportunities.bulk_create(new_opportunities, ignore_conflicts=True)
    # Re-read the persisted rows: a row that lost the unique-constraint race to a concurrent
    # persist must surface with its persisted id, not this call's never-inserted UUID.
    return list(team_opportunities.filter(fingerprint__in=[o.fingerprint for o in new_opportunities]))
