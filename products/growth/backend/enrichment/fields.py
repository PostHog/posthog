"""Typed field registry for firmographic enrichment.

The single source of truth every enrichment writer imports, so the Postgres record,
the ClickHouse group-property projection, and the at-signup snapshot stay in lockstep.
Provider-agnostic: providers transform their responses into this shape. icp_score is
intentionally excluded from v0.

Precedent: ee/billing/salesforce_enrichment/usage_signals.py (UsageSignals).
"""

import dataclasses
from typing import Any, Optional

# Prefix for the `enrichment_*` ClickHouse group properties written via group_identify.
ENRICHMENT_PROPERTY_PREFIX = "enrichment_"


@dataclasses.dataclass
class EnrichmentFields:
    """Firmographic enrichment values for one organization."""

    company_type: Optional[str] = None
    headcount: Optional[int] = None
    headcount_engineering: Optional[int] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    founded_year: Optional[int] = None
    funding_stage: Optional[str] = None
    is_yc_company: Optional[bool] = None

    def to_dict(self) -> dict[str, Any]:
        """Return set (non-None) fields keyed by registry name."""
        return {
            field.name: value for field in dataclasses.fields(self) if (value := getattr(self, field.name)) is not None
        }

    def to_group_properties(self) -> dict[str, Any]:
        """Return the `enrichment_*` group properties for the ClickHouse projection."""
        return {f"{ENRICHMENT_PROPERTY_PREFIX}{name}": value for name, value in self.to_dict().items()}
