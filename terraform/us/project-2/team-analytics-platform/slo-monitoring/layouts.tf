locals {
  slo_operation_layout_y = {
    for op_idx, op_key in sort(keys(local.slo_operations)) :
    op_key => 6 + sum(concat(
      [0],
      [
        for previous_op_key in slice(sort(keys(local.slo_operations)), 0, op_idx) :
        1 + length(local.slo_operations[previous_op_key].regions) * 3
      ]
    ))
  }
}

resource "posthog_dashboard_layout" "slo_monitoring" {
  dashboard_id = posthog_dashboard.slo_monitoring.id
  tiles = concat(
    # Row 0 (y=0, h=5): Success rate + volume table.
    [
      {
        insight_id = posthog_insight.slo_success_rate.id
        layouts_json = jsonencode({
          sm = {
            h    = 5, i = "success_rate", w = 8, x = 0, y = 0
            minH = 2, minW = 2, moved = false, static = false
          }
        })
      },
      {
        insight_id = posthog_insight.slo_volume.id
        layouts_json = jsonencode({
          sm = {
            h    = 5, i = "volume", w = 4, x = 8, y = 0
            minH = 2, minW = 2, moved = false, static = false
          }
        })
      },
      {
        text_body = "**Success rate** is a 28-day rolling window showing the percentage of successful operations. **Burn rate** shows how fast you're consuming your error budget on a logarithmic scale — the Budget rate line marks sustainable consumption, crossing 100x burn indicates an active incident. **Duration** shows p50/p95/p99 operation latency in seconds."
        layouts_json = jsonencode({
          sm = {
            h    = 1, i = "text", w = 12, x = 0, y = 5
            minH = 1, minW = 1, moved = false, static = false
          }
        })
      },
    ],
    # Per-operation sections: header + burn rate (left) + duration (right) per region.
    # Each section: header (h=1) + N regions * row_height (h=3).
    # Base y = 6 (after success rate h=5 + text h=1).
    flatten([
      for op_key in sort(keys(local.slo_operations)) : concat(
        # Section header
        [{
          text_body = "## ${local.slo_operations[op_key].name}"
          layouts_json = jsonencode({
            sm = {
              h    = 1, i = "header_${op_key}", w = 12, x = 0,
              y    = local.slo_operation_layout_y[op_key]
              minH = 1, minW = 1, moved = false, static = false
            }
          })
        }],
        # Burn rate tiles (left half)
        [
          for reg_idx, region in sort(local.slo_operations[op_key].regions) : {
            insight_id = posthog_insight.slo_burn_rate["${op_key}_${lower(region)}"].id
            layouts_json = jsonencode({
              sm = {
                h    = 3, i = "burn_${op_key}_${lower(region)}", w = 6, x = 0,
                y    = local.slo_operation_layout_y[op_key] + 1 + reg_idx * 3
                minH = 2, minW = 2, moved = false, static = false
              }
            })
          }
        ],
        # Duration tiles (right half)
        [
          for reg_idx, region in sort(local.slo_operations[op_key].regions) : {
            insight_id = posthog_insight.slo_duration["${op_key}_${lower(region)}"].id
            layouts_json = jsonencode({
              sm = {
                h    = 3, i = "dur_${op_key}_${lower(region)}", w = 6, x = 6,
                y    = local.slo_operation_layout_y[op_key] + 1 + reg_idx * 3
                minH = 2, minW = 2, moved = false, static = false
              }
            })
          }
        ],
      )
    ]),
  )
}
