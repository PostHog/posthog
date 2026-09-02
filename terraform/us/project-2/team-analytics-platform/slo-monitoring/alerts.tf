resource "posthog_alert" "alert_delivery_slo" {
  for_each = posthog_insight.alert_delivery_failure_rate

  name                   = "Alert notification delivery SLO breach (${each.key})"
  enabled                = true
  calculation_interval   = "daily"
  condition_type         = "absolute_value"
  threshold_type         = "absolute"
  threshold_upper        = 0.0005
  series_index           = 0
  check_ongoing_interval = false
  insight                = each.value.id
  subscribed_users       = var.analytics_platform_alert_subscribed_user_ids
}
