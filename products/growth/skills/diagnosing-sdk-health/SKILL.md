---
name: diagnosing-sdk-health
description: >
  Diagnoses the health of a project's PostHog SDK integrations — which SDKs are up to
  date, which are outdated, and what to do about it. Use when a user asks about PostHog
  SDK versions, outdated SDKs, upgrade recommendations, "SDK health", "SDK doctor", or
  when events or features seem off and it might be due to using an old SDK.
---

# Diagnosing SDK health

When a user asks about PostHog SDK versions, outdated SDKs, or whether they should
upgrade, use the pre-digested SDK Doctor report rather than reasoning about versions
yourself. The backend applies smart-semver rules (grace periods, minor-count thresholds,
age-based detection), traffic-percentage thresholds, and provides user-facing copy that
matches the SDK Doctor UI exactly.

## Available tools

| Tool                     | Purpose                                                                                              |
| ------------------------ | ---------------------------------------------------------------------------------------------------- |
| `posthog:sdk-doctor-get` | Returns a structured health report plus UI-matching copy and drill-in URLs per SDK/version.          |
| `posthog:execute-sql`    | (Optional) Run a `sql_query` from the report to show events captured by a specific outdated version. |

## Workflow

### Step 1 — Invoke the tool

```json
posthog:sdk-doctor-get
{}
```

Pass `force_refresh: true` only when the user explicitly asks for fresh data — by default
the report uses a Redis cache that's refreshed every 12 hours.

### Step 2 — Read the top-level summary

```json
{
  "overall_health": "healthy" | "needs_attention",
  "health": "success" | "warning" | "danger",
  "needs_updating_count": 0,
  "team_sdk_count": 0,
  "sdks": [ /* per-SDK assessments */ ]
}
```

Lead with the headline:

- `overall_health: healthy` — everything's current; say so and stop.
- `health: warning` — some SDKs outdated but less than half of the project's SDKs. Flag
  as upgrade recommendations.
- `health: danger` — majority of team SDKs are outdated. Treat as urgent.

### Step 3 — Surface the banner text(s) verbatim

Each SDK's `banners` array contains zero or more sentences that match the SDK Doctor UI's
"Time for an update!" alert exactly, e.g.:

> Version 7.0.0 of the Python SDK has captured more than 10% of events in the last 7 days.

**Quote these verbatim.** They're what the user already sees (or would see) in the UI —
rewording creates drift between agent and product copy.

### Step 4 — Report per-SDK findings

For each entry in `sdks`, surface:

- `readable_name` (e.g. `Python`, `Node.js`, `Web`) — use this in prose, not the raw `lib`
- `latest_version`
- `severity` (`none` / `warning` / `danger`) — use this to group or color findings

Group by severity (`danger` first, then `warning`, then `none`). Skip SDKs with
`needs_updating: false` unless the user explicitly asked about the full state.

### Step 5 — Per-version drill-down (when the user wants detail)

Each SDK's `releases` array has per-version rows. Each row includes UI-matching copy and
ready-to-use links:

- `status_reason` — badge tooltip text that **closely** matches the UI (e.g. `"Released
5 months ago. Upgrade recommended."`, `"You have the latest available. Click 'Releases ↗'
above to check for any since."`, or `"Released 2 months ago. Upgrading is a good idea,
but it's not urgent yet."`). Quote directly. **Caveat**: the relative-age segment
  ("5 months ago" etc.) is computed with Python's `humanize.naturaltime` on the backend
  and JavaScript's `dayjs().fromNow()` in the browser, and the two libraries have
  different thresholds at some boundaries (e.g. humanize says `"30 days ago"` where dayjs
  says `"a month ago"`; humanize says `"4 months ago"` at 148 days where dayjs says
  `"5 months ago"`). The overall template is identical; the age phrasing may be one
  threshold off. If a user cites an exact age from the UI that doesn't match, don't
  "correct" them — the UI is showing dayjs output and both are internally consistent.
- `released_ago` — human-readable relative age (e.g. `"5 months ago"`) — same
  humanize-vs-dayjs caveat as above.
- `is_outdated`, `is_old`, `is_current_or_newer` — booleans if you need to branch
- `sql_query` — complete SQL statement to see the last 50 events captured by this version.
  Suggest it as a copy-paste snippet OR pass it to `posthog:execute-sql` to drill in.
- `activity_page_url` — relative path (starts with `/project/<id>/`) to the Activity >
  Explore page pre-filtered to this lib + version. Combine with the user's PostHog host
  (e.g. `us.posthog.com`) for a clickable link.

### Step 6 — Link to the UI

Always close with a link to the SDK Doctor page: `/project/<project_id>/health/sdk-doctor`.
The UI shows per-row event counts, last-event timestamps, release notes, and SDK docs
links — more than the tool response includes.

## Interpreting severity

The backend applies these rules (you don't need to re-check them):

- **Grace period**: versions released within the last 7 days (14 days for web) are never
  flagged, even if major versions behind.
- **Minor-version rule**: flag if 3+ minors behind OR > 180 days old.
- **Major-version rule**: always flag if a major version behind (outside grace period).
- **Patch-version rule**: never flagged — patch differences are noise.
- **Age rule** (separate "old" flag): desktop SDKs flagged at > 16 weeks old, mobile at
  > 24 weeks old (mobile is more lenient — users don't auto-update apps).
- **Traffic threshold**: an outdated version handling ≥10% of events (≥20% for web)
  surfaces as a traffic alert even if a newer version is also in use. Mobile SDKs are
  excluded from traffic alerts.
- **Overall severity**: `danger` when half or more of the project's SDKs are outdated,
  `warning` when some are outdated but not majority.

## Copy-faithfulness

These response fields are **user-facing UI copy** — quote them verbatim, don't reword:

- `banners[]` — top-level "Time for an update!" alert text. Byte-for-byte match with UI.
- `releases[].status_reason` — per-version badge tooltip text. Template matches the UI,
  but the relative-age phrasing (`"5 months ago"` etc.) can be one boundary threshold
  off because the backend uses `humanize` and the UI uses `dayjs`. See Step 5 caveat.
- `readable_name` — human-readable SDK name. Byte-for-byte match with UI.

`reason` (per-SDK) is a programmatic summary meant for ranking/filtering, not for quoting
to users. Prefer `banners[]` and `status_reason` for user-visible output.

## Handling empty or errored drill-in fields

If `sql_query` or `activity_page_url` comes back as an empty string for a particular
release, the backend sanitizer rejected the `lib_version` as potentially unsafe to
interpolate (e.g. it contained quote characters or whitespace). When this happens:

- **Surface it** — tell the user "the recorded SDK version string doesn't look safe to
  interpolate into a query, so I can't build a drill-in link for it." This is a signal
  worth noting (it could indicate instrumentation tampering or a library bug).
- **Do NOT retry** — calling the tool again won't change the result.
- **Do NOT patch** — don't rewrite the version or guess at a safe substitute and pipe
  that into `posthog:execute-sql`. That would defeat the sanitizer.

Similarly, if you pass `sql_query` to `posthog:execute-sql` and it errors, surface the
error verbatim rather than rewriting the query. The query template is a verbatim mirror
of what the SDK Doctor UI uses — if the UI's SQL wouldn't run, something else is wrong.

**Do not wrap, truncate, or modify `sql_query` in any way before passing to
`posthog:execute-sql`.** No `SELECT * FROM (<sql_query>) LIMIT 10`, no adding `WHERE`
clauses, no changing the ORDER BY, no dropping columns. The query is the verbatim mirror
— if you need something different, build a fresh query from scratch with the user's help,
don't derive it from `sql_query`.

## Deferring to documentation for "why is it still outdated?" questions

When the user expresses confusion about an old SDK version still producing events after
they believed it was updated — phrasings like "I thought I updated", "we already
upgraded", "we deployed the new version but…", "why are users still on the old SDK?",
or any variation of "why isn't it gone?" — do **not** improvise a list of causes. Point
them to the canonical docs page instead:

**https://posthog.com/docs/sdk-doctor/keeping-sdks-current**

That page is the product team's source of truth on why versions persist (HTML snippet
pinning, lockfiles in separate apps, CDN or browser caching, service workers,
build/deploy issues) and what to do about each one (auto vs. manual update paths per
SDK). It has diagrams, product-specific language, and will stay up to date as the
guidance evolves — your improvised version will drift.

Suggested response shape:

> That's a common question with a few possible causes — cached bundles, pinned snippet
> versions, lockfiles in separate apps, service workers, build/deploy issues, etc.
> Rather than guess which one's biting you, have a look at
> [Keeping SDKs current](https://posthog.com/docs/sdk-doctor/keeping-sdks-current) —
> it walks through each cause and the fix. Once you've skimmed it, I can help you narrow
> it down for your setup (e.g. by pulling the activity events for the outdated version
> to see whether it's one app/domain/subpath or spread across everything).

**The trigger is intent, not content.** Defer whenever the user expresses surprise or
confusion about persistence ("still", "thought I updated", "why haven't users upgraded",
"why is the old one still there"), even when the tool response technically contains the
version's age, reason, or traffic breakdown. The docs page exists because the literal
data doesn't answer _why_, just _what_.

### When NOT to defer

Do **not** send the user to the docs page when:

- The question is about a **specific field** in the response — e.g. "what does `is_old`
  mean?" or "how is severity calculated?" — answer directly using the report fields or
  the "Interpreting severity" rules below.
- The user is asking for the **raw data** (events, versions in use, counts, persons) —
  pull it via the report or `posthog:execute-sql` and present it.
- The user has already read the page and is asking a **specific follow-up** — answer
  directly or pull data to help narrow things down.

## Tips

- If `team_sdk_count` is 0, the project isn't sending events with SDK metadata. Suggest
  checking that `posthog-js` (or another SDK) is actually installed and capturing events.
- The report is per-project. If the user asks about multiple projects, invoke the tool
  once per project (after switching project context via `posthog:switch-project`).
- The tool is read-only. No side effects, no rate limits, safe to call anytime.
- For "show me the events from this outdated version" requests, you have three options,
  ordered from most to least interactive:
  1. Render a clickable link from `activity_page_url` — user explores in PostHog UI.
  2. Pass `sql_query` to `posthog:execute-sql` and summarize the result inline.
  3. Quote the `sql_query` as a copy-paste snippet.

## Phrasing the drill-in offer

When you offer to open `activity_page_url` or run `sql_query`, describe what the user
will see in terms of the SDK being old, not the page or person. The data is about the
customer's **end-users' events captured while an old SDK is loaded** — the old thing is
the SDK, not the page or person.

- Good: "Want me to pull up the events captured by this old SDK so you can see which
  pages on your site are still loading it, and which end-users are hitting them?"
- Good: "I can show you which URLs on the site are still serving the outdated SDK and
  who's generating events from them."
- Avoid: "Want to see which pages/persons are still on the old version?" — pages don't
  run SDK versions; visitors of pages do. This phrasing makes the user think the old
  thing is the page or the person, which is wrong.
- Avoid **for web / server SDKs**: "which users are on the old SDK" — users don't install
  these; the customer's deployed app/site does. For **mobile SDKs** (`posthog-ios`,
  `posthog-android`, `posthog-flutter`, `posthog-react-native`), though, "users who
  haven't updated the app" IS accurate — the SDK ships embedded in the app binary and
  users control the update by updating the app. So the rule flips for mobile: phrasings
  like "end-users still running an older app version" or "users who haven't updated to
  the latest release" are correct for mobile drill-ins.
