List error tracking recommendations for the current project. Each row is a server-computed suggestion with a fixed `type` and a type-specific `meta` payload.

Use this when the user asks how to improve their error tracking setup, what they should fix, or wants to act on their recommendations. The list call refreshes recommendations server-side before returning, so the `meta` you get back reflects current state.

Surface only the few recommendations that matter — don't dump every row. Skip ones that are already done or dismissed.

# Response envelope (every recommendation)

- `type`: one of `alerts`, `rate_limits`, `source_maps`, `long_running_issues`.
- `meta`: type-specific payload — see the per-type sections below.
- `completed`: `true` means the recommended action is already satisfied. Nothing to do — skip it.
- `dismissed_at`: set if the user dismissed this recommendation. Skip dismissed ones unless the user explicitly asks.
- `status`: `ready` when `meta` is fresh, `computing` while a refresh is in progress (treat `meta` as possibly stale; re-list shortly to pick up fresh data).
- `computed_at`: when `meta` was last computed.

Only act on recommendations that are not `completed` and not dismissed.

# Recommendation types and what to do

## `alerts` — issue alerts worth enabling

`meta.alerts` is a list of `{ key, enabled }`. Keys: `error-tracking-issue-created` (new issue appears), `error-tracking-issue-reopened` (a resolved issue regresses), `error-tracking-issue-spiking` (volume spikes). `enabled: false` means no alert is wired for that trigger. Completed once all are enabled.

What to do: tell the user which triggers are off and why each is worth turning on. There is no MCP tool to create alerts — direct them to Error tracking → Alerts in the app to enable the missing ones.

## `rate_limits` — ingestion limits to set

`meta.rate_limits` is a list of `{ key, enabled }`. Keys: `project` (project-wide ingestion limit) and `per_issue` (per-issue limit). `enabled: false` means that limit isn't set. Completed once both are set.

What to do: explain that setting limits protects ingestion quota from noisy issues that would otherwise drown out real signal. Set them in Error tracking settings (or via the error tracking settings update tool if it is available in this session).

## `source_maps` — unresolved stack frames

`meta` carries `total_frames`, `unresolved_frames`, `unresolved_pct`, `threshold_pct`, `min_sample_frames`, and `lookback_hours`. It fires when more than `threshold_pct` of recent JS/TS frames are left unresolved over a meaningful sample. Completed when the sample is too small to judge or the unresolved share is at or under the threshold.

What to do: a high unresolved share means stack traces aren't being symbolicated, so errors are hard to read. Inspect current uploads with `error-tracking-symbol-sets-list`. The fix is uploading source maps from the build (posthog-cli or the SDK build step) — there's no upload MCP tool, so guide the user through it. For deeper diagnosis, use the `diagnosing-stacktrace-symbolication` skill.

## `long_running_issues` — old issues still firing

`meta.issues` is a list of `{ id, name, description, created_at, occurrences, status }` for active issues first seen over a week ago that are still recurring. Completed when the list is empty.

What to do: these are stale, unresolved issues worth closing out. For each, inspect with `query-error-tracking-issue` and `query-error-tracking-issue-events`, then act:

- resolve, assign, or change status with `error-tracking-issues-partial-update`
- merge duplicates with `error-tracking-issues-merge-create`
- suppress persistent noise with `error-tracking-suppression-rules-create`

The `investigating-error-issue` and `triaging-error-issues` skills cover the full workflow.

# Next steps

- If any recommendation is `status: computing`, re-list shortly to pick up fresh `meta`.
- After acting on a recommendation, re-list to confirm it flips to `completed: true`.
