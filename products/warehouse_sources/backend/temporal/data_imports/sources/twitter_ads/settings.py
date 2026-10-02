API_VERSION = "12"
ENTITY_TABLES = ("campaigns", "line_items", "promoted_tweets", "funding_instruments", "media_creatives")
STATS_TABLES = {"campaign_stats": "CAMPAIGN", "line_item_stats": "LINE_ITEM"}
PLACEMENTS = ("ALL_ON_TWITTER", "SPOTLIGHT", "TREND")
LOOKBACK_SECONDS = 3 * 24 * 60 * 60
REVOKED_GRANT = "Your X Ads connection is no longer valid. Reconnect your X account, then re-enable the sync."
ACCOUNT_ACCESS_DENIED = (
    "The connected X account cannot access this ad account. Check its ad-account permissions, then reconnect."
)
MISSING_INTEGRATION = "The connected X Ads integration is missing or disconnected. Reconnect your X account."
MISSING_APP = "The PostHog X Ads app is not configured. Contact support."

PRIMARY_KEYS = {
    **{table: ["id"] for table in ENTITY_TABLES},
    **{table: ["entity_id", "date", "placement"] for table in STATS_TABLES},
}
PARTITION_KEYS = {
    **{table: ["created_at"] for table in ENTITY_TABLES},
    **{table: ["date"] for table in STATS_TABLES},
}
