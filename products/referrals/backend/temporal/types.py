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


@dataclass(frozen=True, slots=True)
class IssueShopifyCodesInput:
    """Referral row plus org keys that just flipped ``first_event_sent`` in the prior activity."""

    social_referral_id: str
    flipped_org_keys: list[str]


@dataclass(frozen=True, slots=True)
class ShopifyRewardEmailItem:
    """Payload for enqueueing the referrer reward email (Celery) after Shopify code creation.

    ``shopify_discount_id`` is the Shopify Admin REST ``discount_codes`` resource id when returned by the API.
    """

    user_id: int
    discount_code: str
    shopify_discount_id: str | None
    referee_organization_name: str


@dataclass(frozen=True, slots=True)
class SendShopifyRewardEmailsInput:
    rewards: list[ShopifyRewardEmailItem]
