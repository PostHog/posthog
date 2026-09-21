from dataclasses import replace
from typing import Any

from posthog.exceptions_capture import capture_exception
from posthog.ph_client import get_regional_ph_client

from products.growth.backend.enrichment import gates
from products.growth.backend.enrichment.ai_pilled import (
    current_ai_pilled_label,
    normalize_fit_payload,
    score_with_ai_pilled_label,
)
from products.growth.backend.enrichment.bridge import read_organization_bridge_inputs
from products.growth.backend.enrichment.fit_score import SCORE_VERSION, IcpFitResult
from products.growth.backend.enrichment.icp_lists import CuratedLists, load_active_lists
from products.growth.backend.enrichment.writer import (
    fit_projection_is_current,
    invalidate_fit_projection,
    lock_organization_enrichment,
    merge_into_record,
    project_organization_enrichment,
    write_organization_enrichment,
)
from products.growth.backend.models import EnrichmentLabelResult, OrganizationEnrichment, OrganizationEnrichmentFetch


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
) -> IcpFitResult:
    payload = normalize_fit_payload(fetch.payload)
    if payload is None:
        payload = normalize_fit_payload(latest_matched_payload(str(fetch.organization_id)))
    return score_with_ai_pilled_label(
        payload, fetch=fetch, lists=lists, domain=domain, role=role, wizard_ai_sdk=wizard_ai_sdk
    )


def ai_label_needs_application(result: EnrichmentLabelResult) -> bool:
    lists = load_active_lists()
    if lists is None:
        return False
    if OrganizationEnrichment.objects.filter(
        organization_id=result.organization_id,
        data__icp_fit_ai_label_result_id=str(result.id),
        data__icp_fit_ai_label_projected_result_id=str(result.id),
        data__icp_fit_version=SCORE_VERSION,
        data__icp_fit_lists_version=lists.version,
    ).exists():
        return False
    organization_id = str(result.organization_id)
    identity = gates.resolve_signup_identity(organization_id)
    if not isinstance(identity, gates.SignupIdentity):
        return False
    with lock_organization_enrichment(organization_id):
        fetch = latest_fetch(organization_id)
        if fetch is None or fetch.id != result.fetch_id:
            return False
        current = current_ai_pilled_label(fetch, identity.domain, lists=lists)
        return current is not None and current.id == result.id


def _write_label_score(
    result: EnrichmentLabelResult, domain: str, live_wizard: bool | None, client: Any
) -> IcpFitResult | None:
    organization_id = str(result.organization_id)
    with lock_organization_enrichment(organization_id):
        if not gates.organization_exists(organization_id):
            return None
        record = OrganizationEnrichment.objects.filter(organization_id=organization_id).first()
        data = record.data if record else {}
        fetch = latest_fetch(organization_id)
        if fetch is None or fetch.id != result.fetch_id:
            return None
        lists = load_active_lists()
        if lists is None:
            raise RuntimeError("Cannot apply AI label without active ICP scoring lists")
        current = current_ai_pilled_label(fetch, domain, lists=lists)
        if current is None or current.id != result.id or not ai_label_needs_application(result):
            return None
        flags = data.get("icp_fit_flags")
        persisted_wizard = isinstance(flags, dict) and flags.get("wizard_ai_sdk") is True
        if live_wizard is None and not persisted_wizard:
            raise RuntimeError("Cannot apply AI label without the wizard signal")
        fit = score_archived_fit(
            fetch,
            lists=lists,
            domain=domain,
            role=data.get("signup_role"),
            wizard_ai_sdk=live_wizard if live_wizard is not None else persisted_wizard,
        )
        fit = replace(fit, ai_pilled_label_result_id=str(current.id))
        write_organization_enrichment(
            organization_id=organization_id,
            fields=None,
            pha_client=client,
            fit=fit,
            fit_evaluation_kind="ai_label",
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
        fetch = latest_fetch(organization_id)
        current = current_ai_pilled_label(fetch, domain, lists=lists) if fetch and fetch.id == result.fetch_id else None
        if current is None or current.id != result.id or not fit_projection_is_current(organization_id, fit):
            invalidate_fit_projection(organization_id)
            return False
        if OrganizationEnrichment.objects.filter(
            organization_id=organization_id,
            data__icp_fit_ai_label_result_id=str(result.id),
            data__icp_fit_version=SCORE_VERSION,
            data__icp_fit_lists_version=lists.version,
        ).exists():
            merge_into_record(organization_id, {"icp_fit_ai_label_projected_result_id": str(result.id)})
            return True
        return False


def apply_ai_pilled_label(result: EnrichmentLabelResult) -> bool:
    organization_id = str(result.organization_id)
    if not gates.region_allowed() or not gates.enrichment_enabled() or not ai_label_needs_application(result):
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
        raise RuntimeError("Cannot apply AI label without a regional analytics client")
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
            raise RuntimeError("AI label score projection failed") from delivery_errors[0]
        return current_projection and _mark_label_projection(result, identity.domain, fit)
    finally:
        client.shutdown()
