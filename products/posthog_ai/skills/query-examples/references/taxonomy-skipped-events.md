The team taxonomy query automatically excludes events that are not useful for analytics.
These are events marked as `system` or `ignored_in_assistant` in PostHog's core taxonomy definitions.

## Skipped events

Event | Reason
`$pageleave` | Confuses LLMs — use `$pageview` instead
`$autocapture` | Only useful with autocapture-specific filters
`$$heatmap` | Internal heatmap data, doesn't contribute to event counts
`$copy_autocapture` | Clipboard capture, too niche
`$set` | Person property setting event, not an analytics event
`$opt_in` | Analytics opt-in event, irrelevant for product analytics
`$feature_flag_called` | Feature flag evaluation, not a user action
`$feature_view` | posthog-js/react specific, niche
`$feature_interaction` | posthog-js/react specific, niche
`$capture_metrics` | Internal SDK metrics
`$create_alias` | Identity management event
`$merge_dangerously` | Identity management event
`$groupidentify` | Group identification event

These events are filtered at the SQL level using a `NOT IN` clause, so they don't consume pagination slots.
