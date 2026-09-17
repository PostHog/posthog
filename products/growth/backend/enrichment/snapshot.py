"""At-signup enrichment snapshot.

Captures the firmographic enrichment values as they were at signup, separate from the
live values that later enrichment runs continuously refresh onto the organization group.
The snapshot is emitted once as a person-scoped event and never updated.
"""

import dataclasses
from typing import Any, Optional

from posthoganalytics.client import Client

from products.growth.backend.models import EnrichmentSignupSnapshot

SNAPSHOT_EVENT_NAME = "enrichment_snapshot_at_signup"

SNAPSHOT_PROPERTY_SUFFIX = "_at_signup"


@dataclasses.dataclass(frozen=True)
class SignupEnrichmentSnapshot:
    """PII-light firmographic values captured at signup.

    Only derived firmographic and ICP fields belong here. No raw personal data beyond
    the person association that the emitted event inherently carries.
    """

    company_type: Optional[str] = None
    headcount: Optional[int] = None
    headcount_engineering: Optional[int] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    founded_year: Optional[int] = None
    funding_stage: Optional[str] = None
    is_yc_company: Optional[bool] = None
    # The fit evaluation as it stood at signup. A numeric score snapshots with its version;
    # a score-less evaluation snapshots the status alone, so "insufficient at signup" stays
    # distinguishable from "never evaluated" forever. (The legacy clay icp_score was never
    # fed into the snapshot, so these are the first score keys the event actually carries.)
    icp_fit_score: Optional[int] = None
    icp_fit_version: Optional[str] = None
    icp_fit_status: Optional[str] = None

    def to_event_properties(self) -> dict[str, Any]:
        """Return the snapshot as `*_at_signup` event properties, dropping unset values."""
        return {
            f"{field.name}{SNAPSHOT_PROPERTY_SUFFIX}": value
            for field in dataclasses.fields(self)
            if (value := getattr(self, field.name)) is not None
        }


def capture_signup_enrichment_snapshot(
    pha_client: Client,
    *,
    organization_id: str,
    distinct_id: str,
    snapshot: SignupEnrichmentSnapshot,
) -> bool:
    """Emit the at-signup enrichment snapshot for an org, exactly once.

    Returns True if this call emitted the snapshot, False if one already existed.
    """
    # Claim the write-once slot atomically before emitting: the unique constraint on
    # organization_id lets concurrent or repeated runs make at most one row per org.
    _, created = EnrichmentSignupSnapshot.objects.get_or_create(organization_id=organization_id)
    if not created:
        return False

    # Emit as a person-scoped event (not org group properties): DeletionType.Person erases
    # all of a person's events, while group properties sit outside person-deletion scope,
    # so an erase-by-person request would not remove snapshot values stored on the group.
    pha_client.capture(
        distinct_id=distinct_id,
        event=SNAPSHOT_EVENT_NAME,
        properties=snapshot.to_event_properties(),
        groups={"organization": str(organization_id)},
    )
    return True
