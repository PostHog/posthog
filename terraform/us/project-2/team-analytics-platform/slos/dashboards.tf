resource "posthog_dashboard" "team_analytics_platform_slos" {
  name = "[team-analytics-platform] SLOs"
  pinned = true
  tags = ["managed-by:terraform"]
}
