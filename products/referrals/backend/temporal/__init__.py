"""Two unrelated Temporal surfaces live in this module:

- ``RESEARCH_*`` — hourly Twitter / internal referral research agents, run on TASKS queue
  alongside the sandbox infrastructure they depend on.
- ``STATUS_*`` — nightly social-referral referee state sync, run on the general-purpose
  queue.

The worker imports them as separate aliases so each set lands on its own queue.
"""

from products.referrals.backend.temporal.activities import (
    referral_status_issue_shopify_codes_activity,
    referral_status_list_pending_ingestion_activity,
    referral_status_process_single_ingestion_activity,
    referral_status_record_ingestion_check_failure_activity,
    referral_status_send_shopify_reward_emails_activity,
    run_internal_referral_research_activity,
    run_twitter_referral_research_activity,
)
from products.referrals.backend.temporal.workflow import SocialReferralStatusWorkflow
from products.referrals.backend.temporal.workflows import (
    InternalReferralResearchWorkflow,
    TwitterReferralResearchWorkflow,
)

RESEARCH_WORKFLOWS = [
    TwitterReferralResearchWorkflow,
    InternalReferralResearchWorkflow,
]

RESEARCH_ACTIVITIES = [
    run_twitter_referral_research_activity,
    run_internal_referral_research_activity,
]

STATUS_WORKFLOWS = [SocialReferralStatusWorkflow]

STATUS_ACTIVITIES = [
    referral_status_list_pending_ingestion_activity,
    referral_status_process_single_ingestion_activity,
    referral_status_issue_shopify_codes_activity,
    referral_status_send_shopify_reward_emails_activity,
    referral_status_record_ingestion_check_failure_activity,
]
