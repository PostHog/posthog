from products.referrals.backend.temporal.activities import (
    referral_status_list_pending_ingestion_activity,
    referral_status_process_single_ingestion_activity,
    referral_status_record_ingestion_check_failure_activity,
)
from products.referrals.backend.temporal.workflow import SocialReferralStatusWorkflow

WORKFLOWS = [SocialReferralStatusWorkflow]

ACTIVITIES = [
    referral_status_list_pending_ingestion_activity,
    referral_status_process_single_ingestion_activity,
    referral_status_record_ingestion_check_failure_activity,
]
