from dataclasses import replace
from typing import Any

from django.db.models import Q

from products.growth.backend.enrichment import gates
from products.growth.backend.enrichment.fit_score import AiPilledLabel, IcpFitResult, score_company
from products.growth.backend.enrichment.harmonic_adapter import normalize_graphql_company
from products.growth.backend.enrichment.icp_lists import CuratedLists, load_active_lists
from products.growth.backend.enrichment.labels import ai_processing_approved
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig, OrganizationEnrichmentFetch


def normalize_fit_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or not payload:
        return None
    if "traction_metrics" in payload or "tags_v2" in payload or "id" in payload:
        return payload if payload.get("id") else None
    return normalize_graphql_company(payload)


def current_ai_pilled_label(
    fetch: OrganizationEnrichmentFetch,
    domain: str | None,
    *,
    lists: CuratedLists | None = None,
    lock_prompt_config: bool = True,
) -> EnrichmentLabelResult | None:
    if not domain or not ai_processing_approved(fetch.organization_id):
        return None
    identity = gates.resolve_signup_identity(str(fetch.organization_id))
    if not isinstance(identity, gates.SignupIdentity) or identity.domain != domain:
        return None
    lists = lists if lists is not None else load_active_lists()
    if lists is None:
        return None
    configs = EnrichmentPromptConfig.objects.filter(name__in=lists.rules.ai_labels, is_active=True).order_by("name")
    if lock_prompt_config:
        configs = configs.select_for_update()
    versions = Q(pk__in=[])
    for config in configs:
        versions |= Q(label_name=config.name, prompt_version=config.version, prompt_hash=config.content_hash)
    results = {
        result.label_name: result
        for result in EnrichmentLabelResult.objects.filter(
            versions, organization_id=fetch.organization_id, fetch=fetch, inputs__signup_domain=domain
        )
    }
    candidates = [results[name] for name in lists.rules.ai_labels if name in results]
    return next(
        (result for result in candidates if positive_ai_pilled_label(result) is not None),
        candidates[0] if candidates else None,
    )


def positive_ai_pilled_label(result: EnrichmentLabelResult) -> AiPilledLabel | None:
    output = result.output
    if not isinstance(output, dict) or output.get("ai_pilled") is not True:
        return None
    meta = output.get("meta")
    if isinstance(meta, dict) and meta.get("skipped"):
        return None
    return AiPilledLabel(
        result_id=str(result.id),
        fetch_id=str(result.fetch_id),
        prompt_version=result.prompt_version,
        prompt_hash=result.prompt_hash,
    )


def score_with_ai_pilled_label(
    payload: dict[str, Any] | None,
    *,
    fetch: OrganizationEnrichmentFetch | None,
    lists: CuratedLists,
    domain: str | None,
    role: str | None = None,
    wizard_ai_sdk: bool = False,
    lock_prompt_config: bool = True,
) -> IcpFitResult:
    label = None
    if fetch is not None and normalize_fit_payload(fetch.payload) == payload:
        label = current_ai_pilled_label(fetch, domain, lists=lists, lock_prompt_config=lock_prompt_config)
    positive_label = positive_ai_pilled_label(label) if label is not None else None
    result = score_company(
        payload,
        lists=lists,
        role=role,
        domain=domain,
        wizard_ai_sdk=wizard_ai_sdk,
        ai_pilled_label=positive_label,
    )
    return replace(result, ai_pilled_label_result_id=str(label.id) if label is not None else None)
