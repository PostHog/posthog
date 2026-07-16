"""Writers for the live enrichment stores.

Orchestration-agnostic: plain functions any orchestrator (the real-time Temporal
workflow, a later batch Dagster asset) can call. Two of the three stores are written
here — the Postgres record read in-request and the ClickHouse group-property
projection. The at-signup person-event snapshot is a separate write-once store.

One writer per field: this owns the provider-derived registry keys. It never touches
`company_type_deterministic`, which the signup classifier owns.
"""

from typing import Any, Optional

from django.db import transaction

from posthoganalytics.client import Client

from posthog.exceptions_capture import capture_exception

from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.score import SCORE_VERSION
from products.growth.backend.models import OrganizationEnrichment, OrganizationEnrichmentFetch

ORGANIZATION_GROUP_TYPE = "organization"


def _merge_into_record(organization_id: str, values: dict[str, Any]) -> None:
    """Row-locked read/merge/save into OrganizationEnrichment.data.

    select_for_update serializes concurrent writers on the same org (the request-path
    signup write and the fire-and-forget provider write). Without the lock they read the
    same snapshot and the later save clobbers the other's keys, dropping enrichment data.
    """
    with transaction.atomic():
        record, _ = OrganizationEnrichment.objects.select_for_update().get_or_create(organization_id=organization_id)
        record.data = {**record.data, **values}
        record.save(update_fields=["data", "updated_at"])


def write_organization_enrichment(
    *,
    organization_id: str,
    fields: EnrichmentFields,
    pha_client: Client,
    icp_score: Optional[int] = None,
) -> None:
    """Persist enrichment to Postgres and project it onto the organization group.

    - Postgres: merge the set registry fields into OrganizationEnrichment.data, preserving
      any keys owned by other writers (e.g. company_type_deterministic).
    - ClickHouse: project `enrichment_*` group properties via group_identify.

    The score rides along on both stores when the caller computed one, version-stamped so a
    later formula revision is distinguishable. `icp_score` is the key Clay also writes: during
    the overlap the two agree, and per-key merge makes last-write-wins safe either way.

    No-op when there are no set fields, so a Harmonic miss leaves both stores untouched.
    """
    values = fields.to_dict()
    if not values:
        return

    if icp_score is not None:
        values = {**values, "icp_score": icp_score, "icp_score_version": SCORE_VERSION}

    _merge_into_record(organization_id, values)

    properties = fields.to_group_properties()
    if icp_score is not None:
        properties = {**properties, "icp_score": icp_score, "icp_score_version": SCORE_VERSION}

    pha_client.group_identify(
        ORGANIZATION_GROUP_TYPE,
        str(organization_id),
        properties=properties,
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


def record_signup_work_email(*, organization_id: str, work_email: bool) -> None:
    """Persist whether the signup used a work email (vs a generic personal domain).

    First-party data known synchronously at signup, so it is written from the request
    path for every signup — including personal-domain ones that never get a provider
    lookup. Postgres only for v0: work_email is never set by the provider transform, and
    personal domains get no provider write, so there's no group projection here. Projecting
    it onto the organization group is deferred until a consumer needs the group property.
    """
    _merge_into_record(organization_id, {"work_email": work_email})
