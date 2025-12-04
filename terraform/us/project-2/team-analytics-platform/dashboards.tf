resource "posthog_dashboard" "team_analytics_platform_key_metrics_dashboard" {
  name        = "[Team: Analytics-Platform] Key Metrics"
  description = "This dashboard contains key metrics useful for the Analytics Platform team."
  pinned      = true
  tags        = ["managed-by:terraform"]
}
