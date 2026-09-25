from dataclasses import replace
from typing import Any

from django.db.models import OuterRef, Subquery

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.growth.backend.enrichment import gates
from products.growth.backend.enrichment.fit_recomputation import latest_matched_payload
from products.growth.backend.enrichment.fit_score import IcpFitResult, score_context
from products.growth.backend.enrichment.icp_lists import CuratedLists, build_curated_lists
from products.growth.backend.enrichment.scoring_context import (
    load_scoring_context,
    normalize_fit_payload,
    saved_wizard_ai_sdk,
)
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
    context = load_scoring_context(
        payload,
        fetch=fetch,
        lists=lists,
        role=role,
        domain=domain,
        wizard_ai_sdk=wizard_ai_sdk,
        lock_prompt_config=False,
    )
    try:
        result = score_context(
            context.values,
            source=lists.rules.source,
            lists_version=lists.version,
            input_versions=context.input_versions,
        )
        return _FormulaEvaluation(inputs=context.values, result=result, error=None)
    except Exception as error:
        capture_exception(error, {"path": "preview_scoring_formula", "scoring_version": lists.version})
        return _FormulaEvaluation(
            inputs=context.values, result=None, error=f"{type(error).__name__}: {str(error)[:1000]}"
        )


def preview_company(
    fetch: OrganizationEnrichmentFetch, active: CuratedLists, candidate: CuratedLists
) -> ScoringPreviewRow:
    record = OrganizationEnrichment.objects.filter(organization_id=fetch.organization_id).first()
    data = record.data if record and isinstance(record.data, dict) else {}
    identity = gates.resolve_signup_identity(str(fetch.organization_id))
    domain = identity.domain if isinstance(identity, gates.SignupIdentity) else None
    wizard = saved_wizard_ai_sdk(data)
    payload = normalize_fit_payload(fetch.payload)
    if payload is None:
        payload = normalize_fit_payload(latest_matched_payload(str(fetch.organization_id)))
    arguments: dict[str, Any] = {
        "fetch": fetch,
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
    candidate_lists = replace(base_lists, rules=parse_scoring_rules({"source": source}))
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
    return [preview_company(fetch, active_lists, candidate_lists) for fetch in fetches]
