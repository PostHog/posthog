resource "posthog_dashboard_layout" "pulse_health" {
  dashboard_id = posthog_dashboard.pulse_health.id
  tiles = [
    # Row 0: what this dashboard measures.
    {
      text_body = "**Volume** shows how many briefs generate and how often they fail or come back quiet. **Action rate** is the primary adoption metric: opportunities acted on over opportunities surfaced. **Helpfulness** charts explicit votes. **Attention retention** counts weekly brief viewers and how many return week-over-week. **Investigation** and **emit** panels watch generation quality: step failures, truncation pile-ups, and best-effort signal emits that would otherwise fail silently."
      layouts_json = jsonencode({
        sm = {
          h    = 1, i = "intro", w = 12, x = 0, y = 0
          minH = 1, minW = 1, moved = false, static = false
        }
      })
    },
    # Row 1: generation volume + action rate.
    {
      insight_id = posthog_insight.pulse_generation_volume.id
      layouts_json = jsonencode({
        sm = {
          h    = 4, i = "generation_volume", w = 6, x = 0, y = 1
          minH = 2, minW = 2, moved = false, static = false
        }
      })
    },
    {
      insight_id = posthog_insight.pulse_action_rate.id
      layouts_json = jsonencode({
        sm = {
          h    = 4, i = "action_rate", w = 6, x = 6, y = 1
          minH = 2, minW = 2, moved = false, static = false
        }
      })
    },
    # Row 2: helpfulness votes.
    {
      insight_id = posthog_insight.pulse_brief_helpfulness.id
      layouts_json = jsonencode({
        sm = {
          h    = 4, i = "brief_helpfulness", w = 6, x = 0, y = 5
          minH = 2, minW = 2, moved = false, static = false
        }
      })
    },
    {
      insight_id = posthog_insight.pulse_opportunity_helpfulness.id
      layouts_json = jsonencode({
        sm = {
          h    = 4, i = "opportunity_helpfulness", w = 6, x = 6, y = 5
          minH = 2, minW = 2, moved = false, static = false
        }
      })
    },
    # Row 3: attention retention + emit health.
    {
      insight_id = posthog_insight.pulse_attention_retention.id
      layouts_json = jsonencode({
        sm = {
          h    = 4, i = "attention_retention", w = 6, x = 0, y = 9
          minH = 2, minW = 2, moved = false, static = false
        }
      })
    },
    {
      insight_id = posthog_insight.pulse_emit_health.id
      layouts_json = jsonencode({
        sm = {
          h    = 4, i = "emit_health", w = 6, x = 6, y = 9
          minH = 2, minW = 2, moved = false, static = false
        }
      })
    },
    # Row 4: investigation health.
    {
      insight_id = posthog_insight.pulse_investigation_survival.id
      layouts_json = jsonencode({
        sm = {
          h    = 4, i = "investigation_survival", w = 6, x = 0, y = 13
          minH = 2, minW = 2, moved = false, static = false
        }
      })
    },
    {
      insight_id = posthog_insight.pulse_investigation_steps.id
      layouts_json = jsonencode({
        sm = {
          h    = 4, i = "investigation_steps", w = 6, x = 6, y = 13
          minH = 2, minW = 2, moved = false, static = false
        }
      })
    },
  ]
}
