from typing import Any

from posthog.exceptions_capture import capture_exception
from posthog.ph_client import get_regional_ph_client

from products.growth.backend.enrichment import gates
from products.growth.backend.enrichment.bridge import read_organization_bridge_inputs
from products.growth.backend.enrichment.fit_score import SCORE_VERSION, IcpFitResult, score_context, scoring_input_hash
from products.growth.backend.enrichment.icp_lists import CuratedLists, load_active_lists
from products.growth.backend.enrichment.labels import ai_processing_approved
from products.growth.backend.enrichment.scoring_context import (
    ScoringContext,
    load_scoring_context,
    normalize_fit_payload,
    saved_wizard_ai_sdk,
    score_with_saved_inputs,
)
from products.growth.backend.enrichment.writer import (
    fit_projection_is_current,
    invalidate_fit_projection,
    lock_organization_enrichment,
    merge_into_record,
    project_organization_enrichment,
    write_organization_enrichment,
)
from products.growth.backend.models import (
    EnrichmentLabelResult,
    EnrichmentPromptConfig,
    OrganizationEnrichment,
    OrganizationEnrichmentFetch,
)


def latest_matched_payload(organization_id: str) -> dict[str, Any] | None:
    """Use the raw archive on provider misses because transformed fields omit scoring inputs.

    The bounded lookback retains the last matched observation without treating a
    sentinel-only history as a known company.
    """
    payloads = (
        OrganizationEnrichmentFetch.objects.filter(organization_id=organization_id)
        .order_by("-fetched_at", "-id")
        .values_list("payload", flat=True)[:10]
    )
    return next(
        (
            payload
            for payload in payloads
            if isinstance(payload, dict) and payload and payload.get("companyFound") is not False
        ),
        None,
    )


def latest_fetch(organization_id: str) -> OrganizationEnrichmentFetch | None:
    return (
        OrganizationEnrichmentFetch.objects.filter(organization_id=organization_id)
        .order_by("-fetched_at", "-id")
        .first()
    )


def score_archived_fit(
    fetch: OrganizationEnrichmentFetch,
    *,
    lists: CuratedLists,
    domain: str | None,
    role: str | None,
    wizard_ai_sdk: bool,
    lock_prompt_config: bool = True,
) -> IcpFitResult:
    payload = normalize_fit_payload(fetch.payload)
    if payload is None:
        payload = normalize_fit_payload(latest_matched_payload(str(fetch.organization_id)))
    return score_with_saved_inputs(
        payload,
        fetch=fetch,
        lists=lists,
        domain=domain,
        role=role,
        wizard_ai_sdk=wizard_ai_sdk,
        lock_prompt_config=lock_prompt_config,
    )


def _current_result_context(
    result: EnrichmentLabelResult,
    *,
    lists: CuratedLists,
    domain: str,
    data: dict[str, Any],
    wizard_ai_sdk: bool | None = None,
) -> ScoringContext | None:
    fetch = latest_fetch(str(result.organization_id))
    if fetch is None or fetch.id != result.fetch_id:
        return None
    config = (
        EnrichmentPromptConfig.objects.select_for_update()
        .filter(name=result.label_name, version=result.prompt_version, is_active=True)
        .first()
    )
    identity = gates.resolve_signup_identity(str(result.organization_id))
    if (
        config is None
        or config.content_hash != result.prompt_hash
        or not isinstance(identity, gates.SignupIdentity)
        or identity.domain != domain
        or result.inputs.get("signup_domain") != domain
        or not ai_processing_approved(result.organization_id)
    ):
        return None
    payload = normalize_fit_payload(fetch.payload)
    if payload is None:
        payload = normalize_fit_payload(latest_matched_payload(str(result.organization_id)))
    persisted_wizard = saved_wizard_ai_sdk(data)
    context = load_scoring_context(
        payload,
        fetch=fetch,
        lists=lists,
        domain=domain,
        role=data.get("signup_role"),
        wizard_ai_sdk=wizard_ai_sdk if wizard_ai_sdk is not None else persisted_wizard,
    )
    return context


def _application_is_current(data: dict[str, Any], context: ScoringContext, lists: CuratedLists) -> bool:
    input_hash = scoring_input_hash(context.values, context.input_versions)
    return (
        data.get("icp_fit_version") == SCORE_VERSION
        and data.get("icp_fit_lists_version") == lists.version
        and data.get("icp_fit_input_hash") == input_hash
        and data.get("icp_fit_projected_input_hash") == input_hash
    )


def label_needs_application(result: EnrichmentLabelResult) -> bool:
    lists = load_active_lists()
    if lists is None:
        return False
    organization_id = str(result.organization_id)
    identity = gates.resolve_signup_identity(organization_id)
    if not isinstance(identity, gates.SignupIdentity):
        return False
    with lock_organization_enrichment(organization_id):
        record = OrganizationEnrichment.objects.filter(organization_id=organization_id).first()
        data = record.data if record else {}
        context = _current_result_context(result, lists=lists, domain=identity.domain, data=data)
        return context is not None and not _application_is_current(data, context, lists)


def _write_label_score(
    result: EnrichmentLabelResult, domain: str, live_wizard: bool | None, client: Any
) -> IcpFitResult | None:
    organization_id = str(result.organization_id)
    with lock_organization_enrichment(organization_id):
        if not gates.organization_exists(organization_id):
            return None
        record = OrganizationEnrichment.objects.filter(organization_id=organization_id).first()
        data = record.data if record else {}
        lists = load_active_lists()
        if lists is None:
            raise RuntimeError("Cannot update the score without an active scoring configuration")
        persisted_wizard = saved_wizard_ai_sdk(data)
        if live_wizard is None and not persisted_wizard:
            raise RuntimeError("Cannot update the score without the wizard signal")
        context = _current_result_context(result, lists=lists, domain=domain, data=data, wizard_ai_sdk=live_wizard)
        if context is None or _application_is_current(data, context, lists):
            return None
        fit = score_context(
            context.values,
            source=lists.rules.source,
            lists_version=lists.version,
            input_versions=context.input_versions,
        )
        write_organization_enrichment(
            organization_id=organization_id,
            fields=None,
            pha_client=client,
            fit=fit,
            fit_evaluation_kind="enrichment",
            project=False,
        )
        return fit


def _mark_label_projection(result: EnrichmentLabelResult, domain: str, fit: IcpFitResult) -> bool:
    organization_id = str(result.organization_id)
    with lock_organization_enrichment(organization_id):
        lists = load_active_lists()
        if lists is None or lists.version != fit.lists_version:
            invalidate_fit_projection(organization_id)
            return False
        record = OrganizationEnrichment.objects.filter(organization_id=organization_id).first()
        context = _current_result_context(result, lists=lists, domain=domain, data=record.data if record else {})
        if (
            context is None
            or scoring_input_hash(context.values, context.input_versions) != fit.input_hash
            or not fit_projection_is_current(organization_id, fit)
        ):
            invalidate_fit_projection(organization_id)
            return False
        merge_into_record(organization_id, {"icp_fit_projected_input_hash": fit.input_hash})
        return True


def apply_enrichment_result(result: EnrichmentLabelResult) -> bool:
    organization_id = str(result.organization_id)
    if not gates.region_allowed() or not gates.enrichment_enabled() or not label_needs_application(result):
        return False
    identity = gates.resolve_signup_identity(organization_id)
    if not isinstance(identity, gates.SignupIdentity):
        return False
    live_wizard = None
    try:
        live_wizard = read_organization_bridge_inputs(organization_id=organization_id).wizard.ai_sdk_detected
    except Exception as error:
        capture_exception(error, {"organization_id": organization_id})
    delivery_errors: list[Exception] = []

    def on_delivery_error(error: Exception, _batch: Any) -> None:
        delivery_errors.append(error)

    client = get_regional_ph_client(sync_mode=True, timeout=10, max_retries=0, on_error=on_delivery_error)
    if client is None:
        raise RuntimeError("Cannot update the score without a regional analytics client")
    try:
        fit = _write_label_score(result, identity.domain, live_wizard, client)
        if fit is None:
            return False
        current_projection = project_organization_enrichment(
            organization_id=organization_id,
            fields=None,
            pha_client=client,
            fit=fit,
            fit_mirror_distinct_id=identity.distinct_id,
        )
        if delivery_errors:
            invalidate_fit_projection(organization_id)
            raise RuntimeError("Score projection failed") from delivery_errors[0]
        return current_projection and _mark_label_projection(result, identity.domain, fit)
    finally:
        client.shutdown()
