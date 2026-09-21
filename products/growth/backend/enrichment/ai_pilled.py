from dataclasses import replace
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from django.db.models import Q

from products.growth.backend.enrichment import gates
from products.growth.backend.enrichment.evidence import evidence_url_key
from products.growth.backend.enrichment.fit_score import AiPilledEvidence, IcpFitResult, score_company
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
    fetch: OrganizationEnrichmentFetch, domain: str | None, *, lists: CuratedLists | None = None
) -> EnrichmentLabelResult | None:
    if not domain or not ai_processing_approved(fetch.organization_id):
        return None
    identity = gates.resolve_signup_identity(str(fetch.organization_id))
    if not isinstance(identity, gates.SignupIdentity) or identity.domain != domain:
        return None
    lists = lists if lists is not None else load_active_lists()
    if lists is None or "llm" not in lists.rules.ai_sources:
        return None
    configs = (
        EnrichmentPromptConfig.objects.select_for_update()
        .filter(name__in=lists.rules.ai_labels, is_active=True)
        .order_by("name")
    )
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
        (result for result in candidates if supported_ai_pilled_evidence(result, domain) is not None),
        candidates[0] if candidates else None,
    )


def supported_ai_pilled_evidence(result: EnrichmentLabelResult, domain: str) -> AiPilledEvidence | None:
    output = result.output
    if not isinstance(output, dict) or output.get("ai_pilled") is not True:
        return None
    if output.get("evidence_status") != "supported" or output.get("evidence_type") not in (
        "developer_tools",
        "ai_product",
    ):
        return None
    meta = output.get("meta")
    if not isinstance(meta, dict) or meta.get("skipped") or meta.get("evidence_quote_verified") is not True:
        return None
    quote = output.get("evidence_quote")
    if not isinstance(quote, str) or not quote.strip():
        return None
    url = output.get("evidence_url")
    if not isinstance(url, str) or not url.isascii() or not url.isprintable() or "\\" in url:
        return None
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or not host
            or not (host == domain or host.endswith("." + domain))
        ):
            return None
    except ValueError:
        return None
    calls = result.inputs.get("tool_calls") if isinstance(result.inputs, dict) else None
    if not isinstance(calls, list):
        return None
    for call in calls:
        if not isinstance(call, dict) or call.get("name") != "fetch_page":
            continue
        fetched = call.get("result")
        if (
            isinstance(fetched, dict)
            and evidence_url_key(fetched.get("url")) == evidence_url_key(url)
            and isinstance(fetched.get("chars"), int)
            and fetched["chars"] > 0
            and not fetched.get("error")
        ):
            return AiPilledEvidence(
                result_id=str(result.id),
                fetch_id=str(result.fetch_id),
                prompt_version=result.prompt_version,
                prompt_hash=result.prompt_hash,
                evidence_type=cast(Literal["developer_tools", "ai_product"], output["evidence_type"]),
                evidence_url=url,
            )
    return None


def score_with_ai_pilled_label(
    payload: dict[str, Any] | None,
    *,
    fetch: OrganizationEnrichmentFetch | None,
    lists: CuratedLists,
    domain: str | None,
    role: str | None = None,
    wizard_ai_sdk: bool = False,
) -> IcpFitResult:
    label = None
    if fetch is not None and normalize_fit_payload(fetch.payload) == payload:
        label = current_ai_pilled_label(fetch, domain, lists=lists)
    evidence = supported_ai_pilled_evidence(label, domain) if label is not None and domain else None
    result = score_company(
        payload,
        lists=lists,
        role=role,
        domain=domain,
        wizard_ai_sdk=wizard_ai_sdk,
        ai_pilled_evidence=evidence,
    )
    return replace(result, ai_pilled_label_result_id=str(label.id) if label is not None else None)
