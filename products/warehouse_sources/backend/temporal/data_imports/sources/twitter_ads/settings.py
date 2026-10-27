API_VERSION = "12"
ENTITY_TABLES = ("campaigns", "line_items", "promoted_tweets", "funding_instruments", "media_creatives", "lead_forms")
# Lead forms cap `count` at 200 and list newest first with no `sort_by`.
PAGE_SIZES = {"lead_forms": 200}
UNSORTABLE_TABLES = ("media_creatives", "lead_forms")
STATS_TABLES = {"campaign_stats": "CAMPAIGN", "line_item_stats": "LINE_ITEM"}
PLACEMENTS = ("ALL_ON_TWITTER", "SPOTLIGHT", "TREND")
LOOKBACK_SECONDS = 3 * 24 * 60 * 60
# The synchronous stats endpoint we use rejects dates further back than this with a 400;
# X's docs say onboarding backfills should use the (unimplemented) async analytics endpoint instead.
MAX_STATS_BACKFILL_DAYS = 90
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
