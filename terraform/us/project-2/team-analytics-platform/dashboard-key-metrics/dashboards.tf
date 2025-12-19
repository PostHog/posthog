# =============================================================================
# PostHog Dashboards Configuration
# =============================================================================
#
# This file demonstrates how to manage PostHog dashboards using Terraform.
#
# For more information, see:
#   https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/dashboard
# =============================================================================

# Terraform configuration for PostHog dashboard
# Compatible with posthog provider v1.0
# Source dashboard ID: 636477
import {
  to = posthog_dashboard.team_analytics_platform_key_metrics
  id = "636477"
}

resource "posthog_dashboard" "team_analytics_platform_key_metrics" {
  name = "[team-analytics-platform] Key metrics"
  pinned = true
  tags = ["managed-by:terraform"]
}
