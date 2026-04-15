resource "posthog_dashboard" "slo_monitoring" {
  name        = "SLO Monitoring"
  description = "Rolling success rates and burn rates for SLO-tracked operations. Uses slo_operation_completed events. Burn rate of 1.0 = consuming error budget at planned rate."
  pinned      = true
  tags        = ["managed-by:terraform", "slo"]
}
