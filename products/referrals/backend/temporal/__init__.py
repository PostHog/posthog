from products.referrals.backend.temporal.activities import (
    run_internal_referral_research_activity,
    run_twitter_referral_research_activity,
)
from products.referrals.backend.temporal.workflows import (
    InternalReferralResearchWorkflow,
    TwitterReferralResearchWorkflow,
)

WORKFLOWS = [
    TwitterReferralResearchWorkflow,
    InternalReferralResearchWorkflow,
]

ACTIVITIES = [
    run_twitter_referral_research_activity,
    run_internal_referral_research_activity,
]
