from typing import Any

from django.db.models import Q

from posthog.dataclasses import frozen

from products.growth.backend.enrichment import gates
from products.growth.backend.enrichment.fit_score import IcpFitResult, build_scoring_inputs, score_context
from products.growth.backend.enrichment.harmonic_adapter import normalize_graphql_company
from products.growth.backend.enrichment.icp_lists import CuratedLists
from products.growth.backend.enrichment.labels import ai_processing_approved
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig, OrganizationEnrichmentFetch


@frozen
class ScoringContext:
    values: dict[str, Any]
    input_versions: dict[str, str]


def saved_wizard_ai_sdk(data: dict[str, Any]) -> bool:
    signup = data.get("icp_fit_signup")
    if isinstance(signup, dict) and isinstance(signup.get("wizard_ai_sdk"), bool):
        return signup["wizard_ai_sdk"]
    flags = data.get("icp_fit_flags")
    return isinstance(flags, dict) and flags.get("wizard_ai_sdk") is True


def normalize_fit_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or not payload:
        return None
    if "traction_metrics" in payload or "tags_v2" in payload or "id" in payload:
        return payload if payload.get("id") else None
    return normalize_graphql_company(payload)


def load_scoring_context(
    payload: dict[str, Any] | None,
    *,
    fetch: OrganizationEnrichmentFetch | None,
    lists: CuratedLists,
    domain: str | None,
    role: str | None = None,
    wizard_ai_sdk: bool = False,
    lock_prompt_config: bool = True,
) -> ScoringContext:
    enrichments: dict[str, dict[str, Any]] = {}
    input_versions = {"current_fetch": str(fetch.id)} if fetch is not None else {}
    if fetch is not None and normalize_fit_payload(fetch.payload) == payload and domain:
        identity = gates.resolve_signup_identity(str(fetch.organization_id))
        if (
            isinstance(identity, gates.SignupIdentity)
            and identity.domain == domain
            and ai_processing_approved(fetch.organization_id)
        ):
            configs = EnrichmentPromptConfig.objects.filter(is_active=True).order_by("name")
            if lock_prompt_config:
                configs = configs.select_for_update()
            selected_configs = {config.name: config for config in configs}
            versions = Q(pk__in=[])
            for config in selected_configs.values():
                versions |= Q(label_name=config.name, prompt_version=config.version, prompt_hash=config.content_hash)
            results = EnrichmentLabelResult.objects.filter(
                versions, organization_id=fetch.organization_id, fetch=fetch, inputs__signup_domain=domain
            )
            for result in results:
                if not isinstance(result.output, dict):
                    continue
                config = selected_configs[result.label_name]
                enrichments[result.label_name] = {
                    field["key"]: result.output[field["key"]]
                    for field in config.output_fields
                    if field["key"] != "meta" and field["key"] in result.output
                }
                input_versions[f"enrichment/{result.label_name}"] = str(result.id)
    return ScoringContext(
        values=build_scoring_inputs(
            payload,
            lists=lists,
            role=role,
            domain=domain,
            wizard_ai_sdk=wizard_ai_sdk,
            enrichments=enrichments,
        ),
        input_versions=input_versions,
    )


def score_with_saved_inputs(
    payload: dict[str, Any] | None,
    *,
    fetch: OrganizationEnrichmentFetch | None,
    lists: CuratedLists,
    domain: str | None,
    role: str | None = None,
    wizard_ai_sdk: bool = False,
    lock_prompt_config: bool = True,
) -> IcpFitResult:
    context = load_scoring_context(
        payload,
        fetch=fetch,
        lists=lists,
        domain=domain,
        role=role,
        wizard_ai_sdk=wizard_ai_sdk,
        lock_prompt_config=lock_prompt_config,
    )
    return score_context(
        context.values,
        source=lists.rules.source,
        lists_version=lists.version,
        input_versions=context.input_versions,
    )
