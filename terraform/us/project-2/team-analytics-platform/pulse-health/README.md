# Pulse health dashboard

The "How is Pulse doing" dashboard, defined as code.
One `posthog_dashboard`, eight HogQL `posthog_insight`s, and a `posthog_dashboard_layout`, targeting the dogfood project (project id comes from the `posthog_project_id` variable generated at the project terragrunt layer, default `2`).

## Panel ↔ event contract

Every panel reads only pulse capture events.
The authoritative per-event property list lives in `products/pulse/backend/EVENTS.md`; this table maps panels to the events and properties they consume.

| Panel                           | Insight                         | Events                                                                  | Properties consumed                                      |
| ------------------------------- | ------------------------------- | ----------------------------------------------------------------------- | -------------------------------------------------------- |
| Brief generation volume         | `pulse_generation_volume`       | `product_brief_generated`                                               | `status`, `trigger`                                      |
| Opportunity action rate (7d)    | `pulse_action_rate`             | `product_brief_generated`, `opportunity_acted`, `opportunity_dismissed` | `new_opportunity_count`                                  |
| Brief helpfulness               | `pulse_brief_helpfulness`       | `product_brief_feedback` †                                              | `helpful` †, `has_goal` †                                |
| Opportunity helpfulness         | `pulse_opportunity_helpfulness` | `opportunity_feedback` †                                                | `helpful` †, `kind` †                                    |
| Attention retention             | `pulse_attention_retention`     | `product_brief_viewed`                                                  | (person-level uniques only)                              |
| Investigation step survival     | `pulse_investigation_survival`  | `product_brief_generated`                                               | `investigation_step_count`, `investigation_failed_count` |
| Investigation step distribution | `pulse_investigation_steps`     | `product_brief_generated`                                               | `investigation_step_count`                               |
| Signal emit failure rate (7d)   | `pulse_emit_health`             | `product_brief_generated`                                               | `new_opportunity_count`, `emit_failed_count` †           |

† Ships with the pulse helpfulness-voting + instrumentation-audit changes (`product_brief_feedback`, `opportunity_feedback`, and the `emit_failed_count` / `has_goal` properties).
Until those events flow, the two helpfulness panels render empty and the emit panel reads 0% — queries coalesce missing numeric properties to 0, so nothing errors.

Emission sources for the already-live events:

- `product_brief_generated` — `products/pulse/backend/temporal/activities.py` (`_report_brief_generated`)
- `product_brief_viewed` — `products/pulse/frontend/pulseLogic.ts` (`reportBriefViewed`, once per brief per mount)
- `opportunity_acted` / `opportunity_dismissed` / `opportunity_reopened` — `products/pulse/backend/api/opportunity.py` (`_transition`)

## Applying

CI owns the lifecycle (`.github/workflows/terragrunt-posthog.yaml`): a PR touching this directory gets a `terragrunt plan` comment, and merging to master runs `terragrunt apply` automatically.
Review the plan comment before merging — expect 1 dashboard, 8 insights, 1 layout on first creation.

To plan locally instead:

```bash
export POSTHOG_PROVIDER_TF_STATE_BUCKET=<state bucket>
export POSTHOG_PROVIDER_TF_STATE_REGION=<state region>
export POSTHOG_PROVIDER_POSTHOG_API_KEY=<personal API key with dashboard+insight write scopes>

cd terraform/us/project-2/team-analytics-platform/pulse-health
terragrunt init
terragrunt plan
```

Terragrunt generates the provider, backend, and variable files from the parent templates (`terraform/root.hcl` and the region/project/team layers), so the raw module here is not directly `terraform`-runnable without them.
The provider pin (`PostHog/posthog` 1.0.7, terraform >= 1.13.0) lives in `terraform/providers_root.tf.tpl`.
