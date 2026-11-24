FIELD_EXCLUSIONS = {
    # These fields copy warehouse data, and the activity log does not check warehouse access.
    "RecommendationResolution": ["subject", "subject_hash", "customer_id", "campaign_id", "resolved_at"],
}
