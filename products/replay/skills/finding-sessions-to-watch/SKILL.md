---
name: finding-sessions-to-watch
description: >
  Guides a user from "I want to watch recordings but don't know which ones" to a short, high-signal
  list of sessions worth watching. Use when the user asks which sessions or replays to watch, wants
  help finding interesting / useful recordings, says they don't know where to start in session replay,
  or wants to watch sessions about a goal (signup, pricing, onboarding, checkout, a feature, rageclicks,
  errors, mobile, a specific person) without naming exact filters. Turns a vague intent into a focused
  RecordingsQuery via `query-session-recordings-list`, then deep-links the best few and hands off to
  `investigating-replay`. Do NOT use when the user already has a recording/session ID (use
  investigating-replay) or wants the replay for a known error issue (use finding-replay-for-issue).
---

# Finding sessions to watch

Most people open session replay with a goal ("why are signups dropping?") but no idea which of
thousands of recordings to watch. A raw, unfiltered list is the worst possible answer — it buries the
useful sessions in noise. Your job is to turn their intent into a **focused filter**, return a **handful
of high-signal recordings**, and offer to dig into one.

The starting points below are the same ones the product surfaces as "filter templates" — they encode
the jobs people actually use replay for. Treat them as a menu, not a script.

## The one rule

**Never dump an unfiltered recording list.** Always either (a) apply a goal-based filter, or (b) sort by
a signal (activity, errors) so the first few rows are worth a click. If the user's goal is unclear, ask
one short question or offer the menu before querying.

## Available tools

| Tool                                        | Purpose                                                                  |
| ------------------------------------------- | ------------------------------------------------------------------------ |
| `posthog:query-session-recordings-list`     | Find/filter recordings (the workhorse). Returns metadata + `id` per row. |
| `posthog:read-data-schema`                  | Confirm real event names, URLs, and property values before filtering.    |
| `posthog:execute-sql`                       | Collect `$session_id`s for sessions where a specific **event** happened. |
| `posthog:cohorts-list`                      | Resolve a cohort name → id when scoping to a user segment.               |
| `posthog:session-recording-playlist-create` | Save the resulting filter as a saved filter view (`type: 'filters'`).    |

Hand off to the **`investigating-replay`** skill once the user picks a recording to understand in depth.

## Workflow

### 1. Pin down the goal

Map the request to one of the starting points below. If it's vague ("show me something interesting"),
offer 3-4 options rather than guessing, or default to **most active sessions** — `order:
"activity_score"` **with a `duration gt 30` floor** (see the "Most active users" row for why the floor is
required). High signal, no setup.

### 2. Discover before you filter

Event names and URLs vary per project — never assume `$pageview` paths, a `signup_completed` event, or
a person property exists. Confirm with `read-data-schema` (`event_properties`,
`event_property_values`, `entity_property_values`) before putting a value in a filter. If the needed
event/property doesn't exist, say so and suggest the closest available signal.

### 3. Run a minimal query

Call `query-session-recordings-list` with **only** the filters that serve the goal. Recommended settings:

- set `filter_test_accounts: true` (the tool defaults to `false`) to exclude internal users, unless the
  user is debugging their own session.
- `date_from` of `-7d` to `-30d` for goal-based searches; `-3d` for "recent".
- A deliberate `order` — `activity_score` for "interesting", `console_error_count` for "broken",
  `start_time` for "recent".
- `limit: 10` — you want a shortlist, not a dump.

### 4. Triage and present

Don't relay raw rows. Pick the **3-5 most promising** and say why each is worth watching (long active
duration, many errors, reached the key page, high activity score). Deep-link each as
`{posthog_base_url}/replay/{id}` — never `/replay/home?sessionRecordingId={id}`. Note total matches so
the user knows how much is behind the shortlist.

### 5. Offer the next step

- "Want me to walk through one?" → `investigating-replay`.
- "Want to keep watching these?" → save it as a saved filter view with
  `session-recording-playlist-create` (`type: 'filters'` — a filter view, not a `'collection'`, which is
  for manually curated recordings and can't carry filters).

## Starting points → filters

Two filter shapes cover almost everything:

- **Reached a page** → recording metric `visited_page` (`{ "type": "recording", "key": "visited_page",
"operator": "icontains", "value": "/pricing" }`).
- **Did a specific event** (signup, search, rageclick, used a feature) → there is no event-name filter on
  the recordings query, so first collect session IDs with `execute-sql`, then pass them as `session_ids`
  (see the two-step pattern below).

| User goal                                             | Approach                                                                                                                                                                  |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Signup / onboarding / pricing / checkout friction** | `visited_page` `icontains` the relevant path (confirm the real path first). Order `start_time`, or `console_error_count` to surface broken ones.                          |
| **A specific feature**                                | Two-step: `execute-sql` for `$session_id`s where the feature event fired, then `session_ids`. Pair with `visited_page` if the feature lives on one page.                  |
| **Rageclicks / frustration**                          | Two-step on the `$rageclick` event → `session_ids`.                                                                                                                       |
| **Errors / something broken**                         | `properties: [{ "type": "recording", "key": "console_error_count", "operator": "gt", "value": 0 }]`, order `console_error_count`.                                         |
| **A/B test / feature flag**                           | `{ "type": "flag", "key": "<flag-key>", "operator": "flag_evaluates_to", "value": "<variant or true>" }`.                                                                 |
| **A specific person / segment**                       | `person_uuid`, a `person` property filter (e.g. `email`), or a `cohort` filter (`cohorts-list` for the id).                                                               |
| **Mobile / responsive issues**                        | `{ "type": "event", "key": "$device_type", "operator": "exact", "value": ["Mobile"] }`, or `{ "type": "event", "key": "$screen_width", "operator": "lt", "value": 600 }`. |
| **Most active users / "just show me good ones"**      | `order: "activity_score"` **plus a recording-duration floor** — `{ "type": "recording", "key": "duration", "operator": "gt", "value": 30 }`. The floor is not optional: many recordings have a `null` `activity_score`, and ordering by it alone floats those null-score, zero-duration bot/ping sessions to the top. The `duration gt 30` floor drops them so genuinely active sessions surface. (`active_seconds > 0` and `activity_score is_set` do **not** work — junk rows have sub-second `active_seconds` and null scores that `is_set` doesn't exclude.) |
| **Most active pages**                                 | `execute-sql` to rank `$pageview` by URL, then filter recordings by the hottest page's `visited_page`.                                                                    |

### Two-step pattern: "sessions where event X happened"

The recordings query filters by event _properties_, not event _names_. To find sessions that contain a
particular event, collect the session IDs first:

```sql
posthog:execute-sql
SELECT $session_id
FROM events
WHERE event = '$rageclick'          -- or your signup/search/feature event (confirm via read-data-schema)
    AND timestamp > now() - INTERVAL 7 DAY
    AND $session_id != ''
GROUP BY $session_id
ORDER BY max(timestamp) DESC         -- recent first: UUIDs aren't time-ordered, so the LIMIT must keep the freshest sessions
LIMIT 100
```

Then fetch those recordings (some session IDs won't have a recording — that's expected). Pass the same
`date_from` window as the SQL step — with only `session_ids`, the query falls back to its `-3d` default
and would drop sessions whose event was older than that:

```json
posthog:query-session-recordings-list
{ "date_from": "-7d", "session_ids": ["<id1>", "<id2>", "..."] }
```

## Worked example

User: "Why are people bouncing on our pricing page? Show me some sessions."

1. Goal = pricing-page friction → `visited_page` approach.
2. `read-data-schema` (`event_property_values` for `$pathname`) to confirm the path is `/pricing`.
3. Query:

```json
posthog:query-session-recordings-list
{
  "date_from": "-14d",
  "filter_test_accounts": true,
  "order": "activity_score",
  "limit": 10,
  "properties": [
    { "type": "recording", "key": "visited_page", "operator": "icontains", "value": "/pricing" }
  ]
}
```

4. Present the 3-5 most active, each as `{base}/replay/{id}`, noting which lingered or hit errors.
5. Offer to investigate the most promising one (`investigating-replay`) or save it as a saved filter view (`type: 'filters'`).

## Tips

- Prefer one good filter over many — over-filtering returns nothing and reads as "no data".
- If a query returns zero recordings, widen the date range or loosen the filter before concluding there's
  nothing to watch; if it's still empty, recordings may not be captured for that flow (point the user to
  `diagnosing-missing-recordings`).
- `activity_score` is a good proxy for "worth watching" when there's no sharper signal, but **only paired
  with a `duration gt 30` floor** — ordering by `activity_score` alone floats null-score, zero-duration
  bot/ping sessions to the top (see the "Most active users" row). It also rewards raw interaction volume,
  so prefer a goal-based filter (errors, a key page) when you have one.
- Keep the shortlist short. The value is in choosing _for_ the user, not handing back the haystack.
