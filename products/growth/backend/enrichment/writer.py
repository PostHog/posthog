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

import hashlib
import datetime as dt
import dataclasses
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Optional, Union

from django.db import connection, transaction

from posthoganalytics.client import Client

from posthog.exceptions_capture import capture_exception

from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.fit_score import IcpFitResult
from products.growth.backend.enrichment.score import SCORE_VERSION
from products.growth.backend.models import OrganizationEnrichment, OrganizationEnrichmentFetch

ORGANIZATION_GROUP_TYPE = "organization"


@contextmanager
def lock_organization_enrichment(organization_id: str) -> Iterator[None]:
    lock_key = int.from_bytes(
        hashlib.sha256(f"growth-enrichment:{organization_id}".encode()).digest()[:8], "big", signed=True
    )
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])
        yield


# Published in org_icp_fit_current, so these names are a contract and must stay spelled out
# as constants rather than inlined.
HARMONIC_STATUS_KEY = "harmonic_enrichment_status"
HARMONIC_STATUS_AT_KEY = "harmonic_enrichment_status_at"
HARMONIC_URN_KEY = "harmonic_enrichment_urn"

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


def write_harmonic_enrichment_status(
    organization_id: str, *, status: str, observed_at: str, urn: str, pha_client: Client
) -> Optional[str]:
    """Reads the record's stored status inside the same locked write that merges the new one, so a caller can
    tell a genuine transition from a retried batch re-stamping the same status.
    """
    values = {HARMONIC_STATUS_KEY: status, HARMONIC_STATUS_AT_KEY: observed_at, HARMONIC_URN_KEY: urn}
    previous_status: Optional[str] = None

    def _merge(current: dict[str, Any]) -> dict[str, Any]:
        nonlocal previous_status
        previous_status = current.get(HARMONIC_STATUS_KEY)
        return values

    merge_into_record(organization_id, _merge)
    pha_client.group_identify(ORGANIZATION_GROUP_TYPE, organization_id, properties=values)
    return previous_status


def _fit_record_writes(
    fit: IcpFitResult, *, evaluation_kind: str, evaluated_at: dt.datetime
) -> tuple[dict[str, Any], list[str]]:
    """The Postgres (data) writes and key removals for one fit evaluation.

    Removals are derived from the keys this evaluation actually produced, so a scored org
    that is later disqualified loses its stale components and flags, and a score-less
    evaluation (insufficient_data / not_found) strips every numeric key — the status is
    the result. icp_fit_evaluated_at/icp_fit_evaluation_kind sit outside _FIT_NUMERIC_KEYS
    so a score-less evaluation still records when and how it ran.
    """
    values: dict[str, Any] = {
        "icp_fit_status": fit.status,
        "icp_fit_version": fit.version,
        "icp_fit_evaluated_at": evaluated_at.isoformat(),
        "icp_fit_evaluation_kind": evaluation_kind,
    }
    if fit.lists_version:
        values["icp_fit_lists_version"] = fit.lists_version
    if fit.ai_pilled_label_result_id is not None:
        values["icp_fit_ai_label_result_id"] = fit.ai_pilled_label_result_id

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
                "wizard_ai_sdk": fit.wizard_ai_sdk,
                "ai_pilled_source": fit.ai_pilled_source,
                "ai_pilled_label": dataclasses.asdict(fit.ai_pilled_label) if fit.ai_pilled_label is not None else None,
            }.items()
            if value is not None
        }
        if flags:
            values["icp_fit_flags"] = flags
        if fit.dq_reason:
            values["icp_fit_dq_reason"] = fit.dq_reason

    return values, [
        key
        for key in (*_FIT_NUMERIC_KEYS, "icp_fit_ai_label_result_id", "icp_fit_ai_label_projected_result_id")
        if key not in values
    ]


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
    fit_evaluation_kind: Optional[str] = None,
    fit_evaluated_at: Optional[dt.datetime] = None,
    fit_mirror_distinct_id: Optional[str] = None,
    project: bool = True,
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

    `fit_evaluation_kind` (initial | recheck | backfill | sweep | ai_label) is required whenever
    `fit` is given. It and `fit_evaluated_at` (defaulting to now) land on every evaluation,
    including score-less ones, because the sweep overwrites scores in place and the record
    must say which run wrote the current value. Both ride the Postgres record only, not the
    group projection or the person mirror.

    No-op when there are no set fields and no scores, so a Harmonic miss with fit scoring
    degraded leaves the stores untouched.
    """
    values = fields.to_dict() if fields is not None else {}
    remove: list[str] = []

    if icp_score is not None:
        values = {**values, "icp_score": icp_score, "icp_score_version": SCORE_VERSION}
    if fit is not None:
        if fit_evaluation_kind is None:
            raise ValueError("fit_evaluation_kind is required when fit is provided")
        fit_values, remove = _fit_record_writes(
            fit, evaluation_kind=fit_evaluation_kind, evaluated_at=fit_evaluated_at or dt.datetime.now(dt.UTC)
        )
        values = {**values, **fit_values}

    if not values:
        return

    merge_into_record(organization_id, values, remove=remove)
    if project:
        project_organization_enrichment(
            organization_id=organization_id,
            fields=fields,
            pha_client=pha_client,
            icp_score=icp_score,
            mirror_distinct_id=mirror_distinct_id,
            fit=fit,
            fit_mirror_distinct_id=fit_mirror_distinct_id,
        )


def invalidate_fit_projection(organization_id: str) -> None:
    with lock_organization_enrichment(organization_id):
        if OrganizationEnrichment.objects.filter(organization_id=organization_id).exists():
            merge_into_record(organization_id, {}, remove=["icp_fit_ai_label_projected_result_id"])


def fit_projection_is_current(organization_id: str, fit: IcpFitResult) -> bool:
    record = OrganizationEnrichment.objects.filter(organization_id=organization_id).first()
    return (
        record is not None
        and record.data.get("icp_fit_lists_version") == fit.lists_version
        and all(record.data.get(key) == value for key, value in _fit_projection(fit).items())
    )


def project_organization_enrichment(
    *,
    organization_id: str,
    fields: Optional[EnrichmentFields],
    pha_client: Client,
    icp_score: Optional[int] = None,
    mirror_distinct_id: Optional[str] = None,
    fit: Optional[IcpFitResult] = None,
    fit_mirror_distinct_id: Optional[str] = None,
) -> bool:
    try:
        _enqueue_enrichment_projection(
            organization_id=organization_id,
            fields=fields,
            pha_client=pha_client,
            icp_score=icp_score,
            mirror_distinct_id=mirror_distinct_id,
            fit=fit,
            fit_mirror_distinct_id=fit_mirror_distinct_id,
        )
    except Exception:
        if fit is not None:
            invalidate_fit_projection(organization_id)
        raise
    if fit is not None:
        with lock_organization_enrichment(organization_id):
            if not fit_projection_is_current(organization_id, fit):
                invalidate_fit_projection(organization_id)
                return False
    return True


def _enqueue_enrichment_projection(
    *,
    organization_id: str,
    fields: Optional[EnrichmentFields],
    pha_client: Client,
    icp_score: Optional[int] = None,
    mirror_distinct_id: Optional[str] = None,
    fit: Optional[IcpFitResult] = None,
    fit_mirror_distinct_id: Optional[str] = None,
) -> None:
    properties = fields.to_group_properties() if fields is not None else {}
    if icp_score is not None:
        properties = {**properties, "icp_score": icp_score, "icp_score_version": SCORE_VERSION}
    if fit is not None:
        properties = {**properties, **_fit_projection(fit)}

    if properties:
        event_id = pha_client.group_identify(
            ORGANIZATION_GROUP_TYPE,
            str(organization_id),
            properties=properties,
        )
        if fit is not None and event_id is None:
            raise RuntimeError("ICP fit group projection was not queued")

    if icp_score is not None and mirror_distinct_id:
        pha_client.set(
            distinct_id=mirror_distinct_id,
            properties={"icp_score": icp_score, "icp_score_version": SCORE_VERSION},
        )

    if fit is not None and fit_mirror_distinct_id:
        event_id = pha_client.set(
            distinct_id=fit_mirror_distinct_id,
            properties=_fit_projection(fit),
        )
        if event_id is None:
            raise RuntimeError("ICP fit person projection was not queued")


def archive_provider_fetch(
    *, organization_id: str, provider: str, payload: dict[str, Any], is_recheck: bool
) -> OrganizationEnrichmentFetch | None:
    """Append one raw provider-response row to the fetch archive.

    Never raises: a raw-archive failure must not break enrichment — the live-store write and
    the caller's return still happen. One row per fetch, so signup and recheck stay distinct.
    """
    try:
        with lock_organization_enrichment(organization_id):
            return OrganizationEnrichmentFetch.objects.create(
                organization_id=organization_id,
                provider=provider,
                is_recheck=is_recheck,
                payload=payload,
            )
    except Exception as e:
        capture_exception(e)
        return None


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
