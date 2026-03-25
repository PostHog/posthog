resource "posthog_dashboard_layout" "slo_monitoring" {
  dashboard_id = posthog_dashboard.slo_monitoring.id
  tiles = concat(
    # Row 0 (y=0, h=5): Success rate + volume table.
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
    # Per-region rows: burn rate (left) + duration (right), h=3 each.
    # Sorted by operation then region. Each row is 3 units tall.
    # y starts at 6 (after success rate h=5 + text h=1).
    [
      for idx, key in sort(keys(local.slo_operation_regions)) :
      {
        insight_id = posthog_insight.slo_burn_rate[key].id
        layouts_json = jsonencode({
          sm = {
            h = 3, i = "burn_${key}", w = 6, x = 0, y = 6 + idx * 3
            minH = 2, minW = 2, moved = false, static = false
          }
        })
      }
    ],
    [
      for idx, key in sort(keys(local.slo_operation_regions)) :
      {
        insight_id = posthog_insight.slo_duration[key].id
        layouts_json = jsonencode({
          sm = {
            h = 3, i = "dur_${key}", w = 6, x = 6, y = 6 + idx * 3
            minH = 2, minW = 2, moved = false, static = false
          }
        })
      }
    ],
  )
}
