"""Re-derive enrichment fields from each org's latest archived Harmonic payload and rewrite them.

Generic by design: this re-runs the CURRENT transform_harmonic_company against the stored raw
payload, so it always picks up every field the transform produces at run time -- not just the
fields present when this was written. A later addition to EnrichmentFields therefore backfills
through this same path with no changes here; only the field registry needs to grow.

Safe to re-run: group_identify overwrites the same keys, and a payload that yields no fields is
skipped rather than clearing anything already written.

Also deletes stale suppressed-placeholder values (see SUPPRESSED_PLACEHOLDERS) from the Postgres
record when the current transform no longer derives the key from the same payload. Deletion is
Postgres-only: group properties cannot be deleted, so ClickHouse keeps any historical placeholder
-- measure field completeness on this table's warehouse copy, not on group properties.
"""

import time
from collections.abc import Iterator
from typing import Any

from django.db import transaction

from posthoganalytics.client import Client

from posthog.ph_client import get_client
from posthog.utils import get_instance_region

from products.growth.backend.enrichment.labels import recent_latest_fetches_qs
from products.growth.backend.enrichment.transform import transform_harmonic_company
from products.growth.backend.enrichment.writer import write_organization_enrichment
from products.growth.backend.facade.contracts import FieldsBackfillItem, RegionNotAllowed
from products.growth.backend.models import OrganizationEnrichment

# Values older transform versions wrote for a key that the current transform deliberately
# suppresses when the payload can't substantiate them. Only these exact values are ever deleted,
# so a genuine historical value can't be swept up by an over-eager cleanup.
SUPPRESSED_PLACEHOLDERS: dict[str, frozenset[str]] = {"funding_stage": frozenset({"VENTURE_UNKNOWN"})}


def stale_placeholder_keys(data: dict[str, Any], derived: dict[str, Any]) -> list[str]:
    return [
        key
        for key, placeholders in SUPPRESSED_PLACEHOLDERS.items()
        if key not in derived and data.get(key) in placeholders
    ]


def _strip_stale_placeholders(organization_id: str, derived: dict[str, Any]) -> list[str]:
    # Same row lock as the writer's merge, for the same reason: a concurrent live write must not
    # be clobbered by this read-modify-save.
    with transaction.atomic():
        record = OrganizationEnrichment.objects.select_for_update().filter(organization_id=organization_id).first()
        if record is None:
            return []
        stale = stale_placeholder_keys(record.data, derived)
        if stale:
            record.data = {key: value for key, value in record.data.items() if key not in stale}
            record.save(update_fields=["data", "updated_at"])
        return stale


def ensure_backfill_allowed() -> None:
    # Enrichment is US-only for v0 (mirrors the signup-path region gate).
    if get_instance_region() != "US":
        raise RegionNotAllowed()


def backfill_enrichment_fields(*, limit: int | None, delay: float, dry_run: bool) -> Iterator[FieldsBackfillItem]:
    ensure_backfill_allowed()
    pha_client = get_client()
    return _iter_backfill(pha_client=pha_client, limit=limit, delay=delay, dry_run=dry_run)


def _iter_backfill(
    *, pha_client: Client, limit: int | None, delay: float, dry_run: bool
) -> Iterator[FieldsBackfillItem]:
    fetches = recent_latest_fetches_qs()
    if limit is not None:
        fetches = fetches[:limit]

    for fetch in fetches.iterator():
        organization_id = str(fetch.organization_id)
        payload = fetch.payload
        # `{"companyFound": False}` is core.py's archived placeholder for a genuine provider
        # miss -- a truthy dict that would otherwise sail through the isinstance check below
        # and get scored as a real (if empty) company by transform_harmonic_company.
        if not isinstance(payload, dict) or payload.get("companyFound") is False:
            yield FieldsBackfillItem(organization_id=organization_id, outcome="skipped_no_match")
            continue

        fields = transform_harmonic_company(payload)
        if fields is None:
            yield FieldsBackfillItem(organization_id=organization_id, outcome="skipped_no_match")
            continue

        values = fields.to_dict()
        if not values:
            yield FieldsBackfillItem(organization_id=organization_id, outcome="skipped_empty")
            continue

        if dry_run:
            record = OrganizationEnrichment.objects.filter(organization_id=fetch.organization_id).first()
            stale = stale_placeholder_keys(record.data, values) if record else []
            yield FieldsBackfillItem(
                organization_id=organization_id, outcome="written", fields=tuple(sorted(values)), stripped=tuple(stale)
            )
            continue

        write_organization_enrichment(organization_id=organization_id, fields=fields, pha_client=pha_client)
        stale = _strip_stale_placeholders(organization_id, values)
        yield FieldsBackfillItem(
            organization_id=organization_id, outcome="written", fields=tuple(sorted(values)), stripped=tuple(stale)
        )
        if delay:
            time.sleep(delay)
