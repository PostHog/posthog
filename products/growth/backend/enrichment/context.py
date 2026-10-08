"""The identity and cadence of one enrichment run."""

from enum import StrEnum

from posthog.dataclasses import frozen

# These strings are stored on OrganizationEnrichment.data and captured on events, so a rename
# changes an output contract, not just this module.
FIT_EVALUATION_KIND_INITIAL = "initial"
FIT_EVALUATION_KIND_RECHECK = "recheck"
FIT_EVALUATION_KIND_BACKFILL = "backfill"
FIT_EVALUATION_KIND_SWEEP = "sweep"


class EnrichmentPhase(StrEnum):
    AT_SIGNUP = "at_signup"
    RECHECK = "recheck"
    SWEEP = "sweep"

    @property
    def fit_evaluation_kind(self) -> str:
        match self:
            case EnrichmentPhase.AT_SIGNUP:
                return FIT_EVALUATION_KIND_INITIAL
            case EnrichmentPhase.RECHECK:
                return FIT_EVALUATION_KIND_RECHECK
            case EnrichmentPhase.SWEEP:
                return FIT_EVALUATION_KIND_SWEEP


@frozen
class EnrichmentContext:
    organization_id: str
    domain: str
    phase: EnrichmentPhase
    distinct_id: str | None = None
    role_at_organization: str | None = None
    geoip_country_code: str | None = None

    @property
    def is_recheck(self) -> bool:
        return self.phase is not EnrichmentPhase.AT_SIGNUP
