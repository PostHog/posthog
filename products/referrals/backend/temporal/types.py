"""Inputs for SocialReferral Temporal orchestration."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SocialReferralStatusInputs:
    """Workflow arguments."""

    max_concurrent_referral_checks: int = 25


@dataclass(frozen=True, slots=True)
class ProcessSingleReferralIngestionInput:
    """One SocialReferral row to check for ingestion-stage progression."""

    social_referral_id: str


@dataclass(frozen=True, slots=True)
class RecordIngestionCheckFailureInput:
    """Persist the last Temporal ingestion-check error under ``referee_state.errors.ingestion_sync``."""

    social_referral_id: str
    error_detail: str
