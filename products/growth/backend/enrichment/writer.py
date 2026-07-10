"""Writers for the live enrichment stores.

Orchestration-agnostic: plain functions any orchestrator (the real-time Temporal
workflow, a later batch Dagster asset) can call. Two of the three stores are written
here — the Postgres record read in-request and the ClickHouse group-property
projection. The at-signup person-event snapshot is a separate write-once store.

One writer per field: this owns the provider-derived registry keys. It never touches
`company_type_deterministic`, which the signup classifier owns.
"""

from django.db import transaction

from posthoganalytics.client import Client

from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.models import OrganizationEnrichment

ORGANIZATION_GROUP_TYPE = "organization"


def write_organization_enrichment(
    *,
    organization_id: str,
    fields: EnrichmentFields,
    pha_client: Client,
) -> None:
    """Persist enrichment to Postgres and project it onto the organization group.

    - Postgres: merge the set registry fields into OrganizationEnrichment.data, preserving
      any keys owned by other writers (e.g. company_type_deterministic).
    - ClickHouse: project `enrichment_*` group properties via group_identify.

    No-op when there are no set fields, so a Harmonic miss leaves both stores untouched.
    """
    values = fields.to_dict()
    if not values:
        return

    with transaction.atomic():
        record, _ = OrganizationEnrichment.objects.get_or_create(organization_id=organization_id)
        record.data = {**record.data, **values}
        record.save(update_fields=["data", "updated_at"])

    pha_client.group_identify(
        ORGANIZATION_GROUP_TYPE,
        str(organization_id),
        properties=fields.to_group_properties(),
    )


def record_signup_work_email(*, organization_id: str, work_email: bool) -> None:
    """Persist whether the signup used a work email (vs a generic personal domain).

    First-party data known synchronously at signup, so it is written from the request
    path for every signup — including personal-domain ones that never get a provider
    lookup. Postgres only; the group projection happens with the provider write.
    """
    with transaction.atomic():
        record, _ = OrganizationEnrichment.objects.get_or_create(organization_id=organization_id)
        record.data = {**record.data, "work_email": work_email}
        record.save(update_fields=["data", "updated_at"])
