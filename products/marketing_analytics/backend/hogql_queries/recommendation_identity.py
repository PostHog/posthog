import json
import hashlib
from typing import Protocol, Self

from posthog.schema import (
    MarketingAnalyticsRecommendationIdentity,
    MarketingAnalyticsRecommendationIdentitySourceType as SourceType,
    MarketingAnalyticsRecommendationRule as Rule,
)

from posthog.dataclasses import frozen

# These rules read only Search Console data, which has no ad account, so one decision covers every ad account.
ACCOUNT_AGNOSTIC_RULES = frozenset({Rule.CONTENT_GAP, Rule.KEYWORD_GAP, Rule.STRIKING_DISTANCE})
SEARCH_TERM_RULES = frozenset({Rule.BRAND_OVERLAP, Rule.SPEND_WITHOUT_CONVERSIONS}) | ACCOUNT_AGNOSTIC_RULES
CAMPAIGN_RULES = frozenset({Rule.BRAND_LEAK, Rule.POLICY_LIMITED, Rule.REVIEW_CAMPAIGN, Rule.SCALE_CAMPAIGN})


class InvalidRecommendationIdentity(ValueError):
    pass


class _IdentityFields(Protocol):
    @property
    def rule(self) -> str: ...
    @property
    def source_type(self) -> str: ...
    @property
    def customer_id(self) -> str: ...
    @property
    def campaign_id(self) -> str: ...
    @property
    def subject(self) -> str: ...


@frozen
class RecommendationKey:
    rule: Rule
    source_type: SourceType
    customer_id: str
    campaign_id: str
    subject: str

    @classmethod
    def from_identity(cls, identity: MarketingAnalyticsRecommendationIdentity) -> Self:
        return cls.from_fields(identity)

    @classmethod
    def from_fields(cls, fields: _IdentityFields) -> Self:
        return cls(
            rule=Rule(fields.rule),
            source_type=SourceType(fields.source_type),
            customer_id=fields.customer_id,
            campaign_id=fields.campaign_id,
            subject=fields.subject,
        )

    @property
    def encoded(self) -> str:
        fields = [self.rule.value, self.source_type.value, self.customer_id, self.campaign_id, self.subject]
        return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()


def recommendation_identity(
    rule: Rule,
    customer_id: str | None,
    *,
    campaign_id: str | None = None,
    subject: str | None = None,
    source_type: SourceType = SourceType.GOOGLE_ADS,
) -> MarketingAnalyticsRecommendationIdentity:
    # A resolution must outlive campaign renames and date range changes, so the identity holds ids and search
    # terms, never a campaign name or the campaign that spent the most on a term in the selected range.
    if rule in ACCOUNT_AGNOSTIC_RULES:
        customer_id, campaign_id = None, None
    elif rule in SEARCH_TERM_RULES:
        campaign_id = None
    elif rule == Rule.BUDGET_CONSTRAINED and subject:
        # Campaigns that share a budget get one recommendation, and the campaign that carries it can change.
        campaign_id = None
    elif rule in CAMPAIGN_RULES or rule == Rule.BUDGET_CONSTRAINED:
        subject = None
    else:
        campaign_id, subject = None, None
    return MarketingAnalyticsRecommendationIdentity(
        rule=rule,
        source_type=source_type,
        customer_id=customer_id or "",
        campaign_id=campaign_id or "",
        subject=subject or "",
    )


def validate_identity(identity: MarketingAnalyticsRecommendationIdentity) -> None:
    """Raise InvalidRecommendationIdentity unless the identity's rule can produce it."""
    rule = Rule(identity.rule)
    canonical = recommendation_identity(
        rule,
        identity.customer_id,
        campaign_id=identity.campaign_id,
        subject=identity.subject,
        source_type=SourceType(identity.source_type),
    )
    if canonical != identity:
        raise InvalidRecommendationIdentity(f"A {rule.value} recommendation never has this combination of ids.")
    if rule in SEARCH_TERM_RULES and not identity.subject:
        raise InvalidRecommendationIdentity(f"A {rule.value} recommendation needs the search term as its subject.")
    if rule in CAMPAIGN_RULES and not identity.campaign_id:
        raise InvalidRecommendationIdentity(f"A {rule.value} recommendation needs a campaign_id.")
    if rule == Rule.BUDGET_CONSTRAINED and not (identity.campaign_id or identity.subject):
        raise InvalidRecommendationIdentity(
            "A budget_constrained recommendation needs a campaign_id or a budget id as its subject."
        )
