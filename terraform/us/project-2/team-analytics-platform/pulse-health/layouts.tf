resource "posthog_dashboard_layout" "pulse_health" {
  dashboard_id = posthog_dashboard.pulse_health.id
  tiles = [
    # Row 0: what this dashboard measures.
    {
      text_body = "**Volume** shows how many briefs generate and how often they fail or come back quiet. **Action rate** is the primary adoption metric: opportunities acted on over opportunities surfaced. **Engagement** and **actions by kind** show how many opportunities we create and how many get used versus ignored. **Helpfulness** charts explicit votes. **Attention retention** counts weekly brief viewers and how many return week-over-week. **Investigation** and **emit** panels watch generation quality: step failures, truncation pile-ups, and best-effort signal emits that would otherwise fail silently."
      layouts_json = jsonencode({
        sm = {
          h    = 2, i = "intro", w = 12, x = 0, y = 0
          minH = 1, minW = 1, moved = false, static = false
        }
      })
    },
    # Row 1: generation volume + action rate.
    {
      insight_id = posthog_insight.pulse_generation_volume.id
      layouts_json = jsonencode({
        sm = {
          h    = 4, i = "generation_volume", w = 6, x = 0, y = 2
          minH = 2, minW = 2, moved = false, static = false
        }
      })
    },
    {
      insight_id = posthog_insight.pulse_action_rate.id
      layouts_json = jsonencode({
        sm = {
          h    = 4, i = "action_rate", w = 6, x = 6, y = 2
          minH = 2, minW = 2, moved = false, static = false
        }
      })
    },
    # Row 2: opportunity adoption — creation vs use.
    {
      insight_id = posthog_insight.pulse_opportunity_engagement.id
      layouts_json = jsonencode({
        sm = {
          h    = 4, i = "opportunity_engagement", w = 6, x = 0, y = 6
          minH = 2, minW = 2, moved = false, static = false
        }
      })
    },
    {
      insight_id = posthog_insight.pulse_actions_by_kind.id
      layouts_json = jsonencode({
        sm = {
          h    = 4, i = "actions_by_kind", w = 6, x = 6, y = 6
          minH = 2, minW = 2, moved = false, static = false
        }
      })
    },
    # Row 3: helpfulness votes.
    {
      insight_id = posthog_insight.pulse_brief_helpfulness.id
      layouts_json = jsonencode({
        sm = {
          h    = 4, i = "brief_helpfulness", w = 6, x = 0, y = 10
          minH = 2, minW = 2, moved = false, static = false
        }
      })
    },
    {
      insight_id = posthog_insight.pulse_opportunity_helpfulness.id
      layouts_json = jsonencode({
        sm = {
          h    = 4, i = "opportunity_helpfulness", w = 6, x = 6, y = 10
          minH = 2, minW = 2, moved = false, static = false
        }
      })
    },
    # Row 4: attention retention + emit health.
    {
      insight_id = posthog_insight.pulse_attention_retention.id
      layouts_json = jsonencode({
        sm = {
          h    = 4, i = "attention_retention", w = 6, x = 0, y = 14
          minH = 2, minW = 2, moved = false, static = false
        }
      })
    },
    {
      insight_id = posthog_insight.pulse_emit_health.id
      layouts_json = jsonencode({
        sm = {
          h    = 4, i = "emit_health", w = 6, x = 6, y = 14
          minH = 2, minW = 2, moved = false, static = false
        }
      })
    },
    # Row 5: investigation health.
    {
      insight_id = posthog_insight.pulse_investigation_survival.id
      layouts_json = jsonencode({
        sm = {
          h    = 4, i = "investigation_survival", w = 6, x = 0, y = 18
          minH = 2, minW = 2, moved = false, static = false
        }
      })
    },
    {
      insight_id = posthog_insight.pulse_investigation_steps.id
      layouts_json = jsonencode({
        sm = {
          h    = 4, i = "investigation_steps", w = 6, x = 6, y = 18
          minH = 2, minW = 2, moved = false, static = false
        }
      })
    },
  ]
}
