resource "posthog_dashboard_layout" "slo_monitoring" {
  dashboard_id = posthog_dashboard.slo_monitoring.id
  tiles = concat(
    # Row 0: Success rate (wide) + volume table (narrow).
    [
      {
        insight_id = posthog_insight.slo_success_rate.id
        layouts_json = jsonencode({
          sm = {
            h = 5, i = "success_rate", w = 8, x = 0, y = 0
            minH = 2, minW = 2, moved = false, static = false
          }
        })
      },
      {
        insight_id = posthog_insight.slo_volume.id
        layouts_json = jsonencode({
          sm = {
            h = 5, i = "volume", w = 4, x = 8, y = 0
            minH = 2, minW = 2, moved = false, static = false
          }
        })
      },
      {
        text_body = "**Success rate** is a 28-day rolling window showing the percentage of successful operations. **Burn rate** measures how fast you're consuming your error budget — 1.0 means you're spending at the sustainable rate, >1.0 means you'll exhaust it before the window ends. **Duration** shows p50/p95/p99 operation latency in seconds."
        layouts_json = jsonencode({
          sm = {
            h = 1, i = "text", w = 12, x = 0, y = 5
            minH = 1, minW = 1, moved = false, static = false
          }
        })
      },
    ],
    # Per-operation section: header + burn rates by region (row 1) + durations by region (row 2).
    # Each operation block is: 1 (header) + 3 (burn rates) + 3 (durations) = 7 units tall.
    flatten([
      for op_idx, op_key in sort(keys(local.slo_operations)) :
      concat(
        # Section header
        [
          {
            text_body = "### ${local.slo_operations[op_key].name} (SLO: ${local.slo_operations[op_key].slo}%)"
            layouts_json = jsonencode({
              sm = {
                h = 1, i = "header_${op_key}", w = 12, x = 0, y = 6 + op_idx * 7
                minH = 1, minW = 1, moved = false, static = false
              }
            })
          },
        ],
        # Burn rate tiles for each region (side by side, h=3)
        [
          for reg_idx, region in local.slo_operations[op_key].regions :
          {
            insight_id = posthog_insight.slo_burn_rate["${op_key}_${lower(region)}"].id
            layouts_json = jsonencode({
              sm = {
                h = 3, i = "burn_${op_key}_${lower(region)}"
                w = floor(12 / length(local.slo_operations[op_key].regions))
                x = reg_idx * floor(12 / length(local.slo_operations[op_key].regions))
                y = 7 + op_idx * 7
                minH = 2, minW = 2, moved = false, static = false
              }
            })
          }
        ],
        # Duration tiles for each region (side by side, h=3)
        [
          for reg_idx, region in local.slo_operations[op_key].regions :
          {
            insight_id = posthog_insight.slo_duration["${op_key}_${lower(region)}"].id
            layouts_json = jsonencode({
              sm = {
                h = 3, i = "dur_${op_key}_${lower(region)}"
                w = floor(12 / length(local.slo_operations[op_key].regions))
                x = reg_idx * floor(12 / length(local.slo_operations[op_key].regions))
                y = 10 + op_idx * 7
                minH = 2, minW = 2, moved = false, static = false
              }
            })
          }
        ],
      )
    ]),
  )
}
