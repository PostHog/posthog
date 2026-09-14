"""The identity and cadence of one enrichment run."""

from enum import StrEnum

from posthog.dataclasses import frozen


class EnrichmentPhase(StrEnum):
    AT_SIGNUP = "at_signup"
    RECHECK = "recheck"
    SWEEP = "sweep"


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
