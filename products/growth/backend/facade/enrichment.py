"""Signup-enrichment surface consumed outside products/growth.

Re-exports exactly the symbols that posthog/temporal/signup_enrichment (the core Temporal
workflow that dispatches enrichment) and ee/billing/salesforce_enrichment (which reuses the
Harmonic client and payload helpers for its own dag) rely on today. Internal growth code keeps
importing from the enrichment/ submodules directly rather than through this facade.

The four leading-underscore Harmonic payload helpers and AsyncHarmonicClient are re-exported
verbatim for ee's Salesforce enrichment consumer, not for general external use.
"""

from products.growth.backend.enrichment.core import enrich_organization
from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.harmonic import (
    HARMONIC_BATCH_SIZE,
    AsyncHarmonicClient,
    _extract_primary_tag,
    _is_yc_funded,
    _safe_dict,
    _safe_list,
)
from products.growth.backend.enrichment.providers import HarmonicEnrichmentProvider
from products.growth.backend.enrichment.snapshot import SignupEnrichmentSnapshot, capture_signup_enrichment_snapshot
from products.growth.backend.enrichment.writer import record_signup_work_email
from products.growth.backend.models import OrganizationEnrichment

__all__ = [
    "AsyncHarmonicClient",
    "EnrichmentFields",
    "HARMONIC_BATCH_SIZE",
    "HarmonicEnrichmentProvider",
    "OrganizationEnrichment",
    "SignupEnrichmentSnapshot",
    "_extract_primary_tag",
    "_is_yc_funded",
    "_safe_dict",
    "_safe_list",
    "capture_signup_enrichment_snapshot",
    "enrich_organization",
    "record_signup_work_email",
]
