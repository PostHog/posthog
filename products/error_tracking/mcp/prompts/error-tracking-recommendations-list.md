List error tracking recommendations for the current project. Each row is a server-computed suggestion with a fixed `type` and a type-specific `meta` payload.

Use this when the user asks how to improve their error tracking setup, what they should fix, or wants to act on their recommendations.

Surface only the few recommendations that matter — don't dump every row. Skip ones that are already done or dismissed.

# Response envelope (every recommendation)

- `type`: one of `alerts`, `rate_limits`, `source_maps`, `long_running_issues`.
- `meta`: type-specific payload — see the per-type sections below.
- `completed`: `true` means the recommended action is already satisfied. Nothing to do — skip it.
- `dismissed_at`: set if the user dismissed this recommendation. Skip dismissed ones unless the user explicitly asks.

Only act on recommendations that are not `completed` and not dismissed.

# Recommendation types

- `alerts` — `meta.alerts` is a list of `{ key, enabled }` for the `issue-created`/`issue-reopened`/`issue-spiking` triggers; `enabled: false` means no alert is wired. To act, use the `authoring-error-tracking-alerts` skill (or the `error-tracking-alerts-create` tool).
- `rate_limits` — `meta.rate_limits` is a list of `{ key, enabled }` for the `project` and `per_issue` ingestion limits; `enabled: false` means it isn't set. To act, check and set them via `error-tracking-settings-get` / `error-tracking-settings-update`.
- `source_maps` — `meta` carries frame-resolution stats (`unresolved_pct` vs `threshold_pct` over a sample); a high unresolved share means stack traces aren't symbolicated. The fix is uploading source maps from the build via the setup wizard (append `--region eu` for EU projects):

  ```sh
  npx -y @posthog/wizard@latest upload-source-maps
  ```

  If frames still don't resolve after uploading, use the `diagnosing-stacktrace-symbolication` skill.

- `long_running_issues` — `meta.issues` lists stale active issues (first seen over a week ago, still recurring). To act, use the `triaging-error-issues` skill to work through them, or `investigating-error-issue` to root-cause one.
