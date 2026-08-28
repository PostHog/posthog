"""Writers for the live enrichment stores.

Orchestration-agnostic: plain functions any orchestrator (the real-time Temporal
workflow, a later batch Dagster asset) can call. Two of the three stores are written
here — the Postgres record read in-request and the ClickHouse group-property
projection. The at-signup person-event snapshot is a separate write-once store.

One writer per field: this owns the provider-derived registry keys. It never touches
`company_type_deterministic`, which the signup classifier owns.

Two score families ride along: the legacy clay-parity `icp_score` (kept while its
threshold-tuned consumers migrate) and the ICP fit score on its own `icp_fit_*` keys.
The two never share a key, so neither can misattribute the other's values.
"""

from collections.abc import Callable
from typing import Any, Optional, Union

from django.db import transaction

from posthoganalytics.client import Client

from posthog.exceptions_capture import capture_exception

from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.fit_score import IcpFitResult
from products.growth.backend.enrichment.score import SCORE_VERSION
from products.growth.backend.models import OrganizationEnrichment, OrganizationEnrichmentFetch

ORGANIZATION_GROUP_TYPE = "organization"

# Every fit key tied to one evaluation's numeric outcome. An evaluation that doesn't
# produce one of these strips it, so the record never carries a value the current
# evaluation didn't produce (e.g. components surviving a later disqualification).
_FIT_NUMERIC_KEYS = ["icp_fit_score", "icp_fit_components", "icp_fit_flags", "icp_fit_dq_reason"]


def merge_into_record(
    organization_id: str,
    values: Union[dict[str, Any], Callable[[dict[str, Any]], dict[str, Any]]],
    remove: Optional[list[str]] = None,
) -> None:
    """Row-locked read/merge/save into OrganizationEnrichment.data.

    select_for_update serializes concurrent writers on the same org (the request-path
    signup write and the fire-and-forget provider write). Without the lock they read the
    same snapshot and the later save clobbers the other's keys, dropping enrichment data.

    `values` may be a callable receiving the locked row's current data — needed for a
    merge that depends on the current value (e.g. incrementing a counter) without a
    separate unlocked read racing the lock.

    `remove` deletes keys in the same locked write — used to strip stale fit keys when a
    new evaluation supersedes them.
    """
    with transaction.atomic():
        record, _ = OrganizationEnrichment.objects.select_for_update().get_or_create(organization_id=organization_id)
        computed = values(record.data) if callable(values) else values
        merged = {**record.data, **computed}
        for key in remove or []:
            merged.pop(key, None)
        record.data = merged
        record.save(update_fields=["data", "updated_at"])


def _fit_record_writes(fit: IcpFitResult) -> tuple[dict[str, Any], list[str]]:
    """The Postgres (data) writes and key removals for one fit evaluation.

    Removals are derived from the keys this evaluation actually produced, so a scored org
    that is later disqualified loses its stale components and flags, and a score-less
    evaluation (insufficient_data / not_found) strips every numeric key — the status is
    the result.
    """
    values: dict[str, Any] = {"icp_fit_status": fit.status, "icp_fit_version": fit.version}
    if fit.lists_version:
        values["icp_fit_lists_version"] = fit.lists_version

    if fit.score is not None:
        values["icp_fit_score"] = fit.score
        if fit.components:
            values["icp_fit_components"] = fit.components
        flags = {
            key: value
            for key, value in {
                "quality_investor": fit.quality_investor,
                "data_coverage": fit.data_coverage,
                "low_confidence": fit.low_confidence,
                "agency_flag": fit.agency_flag,
                "nonprofit_flag": fit.nonprofit_flag,
            }.items()
            if value is not None
        }
        if flags:
            values["icp_fit_flags"] = flags
        if fit.dq_reason:
            values["icp_fit_dq_reason"] = fit.dq_reason

    return values, [key for key in _FIT_NUMERIC_KEYS if key not in values]


def _fit_projection(fit: IcpFitResult) -> dict[str, Any]:
    """The fit projection for one evaluation — shared by the ClickHouse group properties
    and the person mirror, since neither store can delete a stale key.

    A score-less evaluation writes only the status key: pairing a fresh `icp_fit_version`
    with a stale numeric `icp_fit_score` would misattribute that number to the new
    evaluation. The (score, version) pair therefore always describes the same evaluation,
    and `icp_fit_status` is the consumer's guard — a score is current only when status is
    scored/disqualified.
    """
    if fit.score is None:
        return {"icp_fit_status": fit.status}
    return {"icp_fit_score": fit.score, "icp_fit_version": fit.version, "icp_fit_status": fit.status}


def write_organization_enrichment(
    *,
    organization_id: str,
    fields: Optional[EnrichmentFields],
    pha_client: Client,
    icp_score: Optional[int] = None,
    mirror_distinct_id: Optional[str] = None,
    fit: Optional[IcpFitResult] = None,
    fit_mirror_distinct_id: Optional[str] = None,
) -> None:
    """Persist enrichment to Postgres and project it onto the organization group.

    - Postgres: merge the set registry fields into OrganizationEnrichment.data, preserving
      any keys owned by other writers (e.g. company_type_deterministic).
    - ClickHouse: project `enrichment_*` group properties via group_identify.

    The legacy clay score rides along on both stores when the caller computed one,
    version-stamped so a later formula revision is distinguishable. `mirror_distinct_id`,
    when the caller passes one, also sets that score on the person's profile: that is
    where Clay writes its own score, and the legacy consumers (the ICP-threshold cohorts
    and their dashboards) read the person property. The caller decides whether mirroring
    is safe here — this function just writes what it's told; see enrich_organization for
    the policy (never sent when it would overwrite a Clay-written person score).

    The fit evaluation writes its own `icp_fit_*` family — status always, numeric keys
    only when this evaluation produced them (see _fit_record_writes) — and mirrors the
    same (score, version, status) or status-only shape onto the person via
    `fit_mirror_distinct_id`, a blind write since nothing else owns that key. Any of the
    three groups (fields / clay score / fit) may be absent: a fields-only write is the
    field backfill, a fit-only write (fields=None) is the score backfill and the
    miss-path status stamp.

    No-op when there are no set fields and no scores, so a Harmonic miss with fit scoring
    degraded leaves the stores untouched.
    """
    values = fields.to_dict() if fields is not None else {}
    remove: list[str] = []

    if icp_score is not None:
        values = {**values, "icp_score": icp_score, "icp_score_version": SCORE_VERSION}
    if fit is not None:
        fit_values, remove = _fit_record_writes(fit)
        values = {**values, **fit_values}

    if not values:
        return

    merge_into_record(organization_id, values, remove=remove)

    properties = fields.to_group_properties() if fields is not None else {}
    if icp_score is not None:
        properties = {**properties, "icp_score": icp_score, "icp_score_version": SCORE_VERSION}
    if fit is not None:
        properties = {**properties, **_fit_projection(fit)}

    if properties:
        pha_client.group_identify(
            ORGANIZATION_GROUP_TYPE,
            str(organization_id),
            properties=properties,
        )

    if icp_score is not None and mirror_distinct_id:
        pha_client.set(
            distinct_id=mirror_distinct_id,
            properties={"icp_score": icp_score, "icp_score_version": SCORE_VERSION},
        )

    if fit is not None and fit_mirror_distinct_id:
        pha_client.set(
            distinct_id=fit_mirror_distinct_id,
            properties=_fit_projection(fit),
        )


def archive_provider_fetch(*, organization_id: str, provider: str, payload: dict[str, Any], is_recheck: bool) -> None:
    """Append one raw provider-response row to the fetch archive.

    Never raises: a raw-archive failure must not break enrichment — the live-store write and
    the caller's return still happen. One row per fetch, so signup and recheck stay distinct.
    """
    try:
        OrganizationEnrichmentFetch.objects.create(
            organization_id=organization_id,
            provider=provider,
            is_recheck=is_recheck,
            payload=payload,
        )
    except Exception as e:
        capture_exception(e)


def record_signup_work_email(*, organization_id: str, work_email: bool, signup_role: Optional[str] = None) -> None:
    """Persist the signup's work-email signal, and its role answer when one was given.

    First-party data known synchronously at signup, so it is written from the request
    path for every signup — including personal-domain ones that never get a provider
    lookup. Postgres only for v0: neither key is set by the provider transform, and
    personal domains get no provider write, so there's no group projection here.

    signup_role makes the fit score's student disqualification replayable from the record
    by any later batch recompute — the role is otherwise only ever in flight on the
    workflow inputs.
    """
    values: dict[str, Any] = {"work_email": work_email}
    if signup_role and signup_role.strip():
        values["signup_role"] = signup_role.strip().lower()
    merge_into_record(organization_id, values)
