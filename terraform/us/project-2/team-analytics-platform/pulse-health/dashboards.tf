resource "posthog_dashboard" "pulse_health" {
  name        = "Pulse health"
  description = "How is Pulse doing: brief generation health, opportunity action rate, helpfulness votes, attention retention, investigation quality, and signal emit health. Built on the pulse product's capture events."
  pinned      = false
  tags        = ["managed-by:terraform", "pulse"]
}
