from dataclasses import replace
from typing import Any

from django.db.models import OuterRef, Subquery

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.growth.backend.enrichment import gates
from products.growth.backend.enrichment.ai_pilled import (
    current_ai_pilled_label,
    normalize_fit_payload,
    positive_ai_pilled_label,
)
from products.growth.backend.enrichment.fit_recomputation import latest_matched_payload
from products.growth.backend.enrichment.fit_score import IcpFitResult, build_scoring_inputs, score_company
from products.growth.backend.enrichment.icp_lists import CuratedLists, build_curated_lists
from products.growth.backend.enrichment.scoring_rules import parse_scoring_rules
from products.growth.backend.models import IcpScoringConfig, OrganizationEnrichment, OrganizationEnrichmentFetch


@frozen
class ScoringPreviewRow:
    company: str
    domain: str | None
    inputs: dict[str, Any]
    active: IcpFitResult | None
    preview: IcpFitResult | None
    error: str | None


@frozen
class _FormulaEvaluation:
    inputs: dict[str, Any]
    result: IcpFitResult | None
    error: str | None


def _evaluate_formula(
    payload: dict[str, Any] | None,
    *,
    fetch: OrganizationEnrichmentFetch | None,
    lists: CuratedLists,
    role: str | None,
    domain: str | None,
    wizard_ai_sdk: bool,
) -> _FormulaEvaluation:
    label = current_ai_pilled_label(fetch, domain, lists=lists, lock_prompt_config=False) if fetch else None
    arguments: dict[str, Any] = {
        "role": role,
        "domain": domain,
        "wizard_ai_sdk": wizard_ai_sdk,
        "ai_pilled_label": positive_ai_pilled_label(label) if label is not None else None,
    }
    inputs = build_scoring_inputs(payload, lists=lists, **arguments)
    try:
        return _FormulaEvaluation(inputs=inputs, result=score_company(payload, lists=lists, **arguments), error=None)
    except Exception as error:
        capture_exception(error, {"path": "preview_scoring_formula", "scoring_version": lists.version})
        return _FormulaEvaluation(inputs=inputs, result=None, error=f"{type(error).__name__}: {str(error)[:1000]}")


def _preview_company(
    fetch: OrganizationEnrichmentFetch, active: CuratedLists, candidate: CuratedLists
) -> ScoringPreviewRow:
    record = OrganizationEnrichment.objects.filter(organization_id=fetch.organization_id).first()
    data = record.data if record and isinstance(record.data, dict) else {}
    identity = gates.resolve_signup_identity(str(fetch.organization_id))
    domain = identity.domain if isinstance(identity, gates.SignupIdentity) else None
    flags = data.get("icp_fit_flags")
    wizard = isinstance(flags, dict) and flags.get("wizard_ai_sdk") is True
    payload = normalize_fit_payload(fetch.payload)
    label_fetch = fetch if payload is not None else None
    if payload is None:
        payload = normalize_fit_payload(latest_matched_payload(str(fetch.organization_id)))
    arguments: dict[str, Any] = {
        "fetch": label_fetch,
        "role": data.get("signup_role"),
        "domain": domain,
        "wizard_ai_sdk": wizard,
    }
    before = _evaluate_formula(payload, lists=active, **arguments)
    after = _evaluate_formula(payload, lists=candidate, **arguments)
    errors = [
        f"{name}: {result.error}"
        for name, result in (("Active formula", before), ("Draft formula", after))
        if result.error
    ]
    company = payload.get("name") if payload else None
    return ScoringPreviewRow(
        company=str(company or fetch.organization.name),
        domain=domain,
        inputs=after.inputs,
        active=before.result,
        preview=after.result,
        error="; ".join(errors) or None,
    )


def preview_scoring_formula(
    active: IcpScoringConfig, base: IcpScoringConfig, source: str, sample: int
) -> list[ScoringPreviewRow]:
    active_lists = build_curated_lists(active)
    base_lists = build_curated_lists(base)
    candidate_lists = replace(
        base_lists, rules=parse_scoring_rules({"source": source, "ai_labels": list(base_lists.rules.ai_labels)})
    )
    latest = (
        OrganizationEnrichmentFetch.objects.filter(organization_id=OuterRef("organization_id"))
        .order_by("-fetched_at", "-id")
        .values("id")[:1]
    )
    fetches = (
        OrganizationEnrichmentFetch.objects.filter(pk=Subquery(latest))
        .select_related("organization")
        .order_by("-fetched_at", "-id")[:sample]
    )
    return [_preview_company(fetch, active_lists, candidate_lists) for fetch in fetches]
