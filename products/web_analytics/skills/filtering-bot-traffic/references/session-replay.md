# Bot traffic and session replay

Session replay is billed per recording, so bot traffic that gets recorded costs money — unlike
analytics, where you can filter bots at query time and move on.
Filtering after the fact does not help here: once a recording is stored, it counts toward usage.
Anything that reduces replay spend has to stop the recording from being captured in the first place.

Use this when someone asks why bots are eating their replay quota, how to stop recording bot or
ad-click traffic, or how much of their replay usage is automated.

## What already happens by default

`posthog-js` drops bot traffic before it sends anything, and this covers replay.
The check runs inside `capture()` ahead of any per-event handling, and `$snapshot` payloads go
through that same `capture()` path — so a detected bot produces no events, no recording, and no
replay usage.

The detection (`isLikelyBot(navigator, custom_blocked_useragents)` in posthog-js) uses three signals:

- the user agent matched against a curated substring blocklist (`DEFAULT_BLOCKED_UA_STRS`)
- `navigator.userAgentData.brands`, matched against the same list
- `navigator.webdriver`

Relevant defaults: `opt_out_useragent_filter: false` (so the filter is **on**) and
`custom_blocked_useragents: []`.

Two consequences worth stating plainly to a customer:

- **A bot that sends a real browser user agent and does not set `navigator.webdriver` is recorded
  and billed.** Nothing in the default path catches it. This is the actual gap behind most
  "bots are consuming my replay credits" reports — typically paid-ad click bots and scrapers
  driving real browser engines, which are exactly the ones that try to look human.
- **An absent or empty user agent is not treated as a bot by the SDK.** `isBlockedUA` returns
  `false` for a falsy UA. Note this differs from the HogQL `isLikelyBot`, where an empty UA
  classifies as a bot — see the measurement gotcha below.

## The "Filter Bot Events" transformation does not cover replay

Do not recommend the CDP `Filter Bot Events` transformation
(`nodejs/src/cdp/templates/_transformations/bot-detection/bot-detection.template.ts`) as a way to
cut replay costs. It is a reasonable assumption and it is wrong.

`$snapshot` never reaches transformations. Replay is split off at capture onto its own endpoint
(`POST /s`, `rust/capture/src/router.rs`) as `DataType::SnapshotMain`, which maps to no analytics
pipeline (`rust/capture/src/v0_request.rs`), lands on its own Kafka topic, and is consumed by
`createSessionReplayPipeline` (`nodejs/src/ingestion/pipelines/sessionreplay/`), which has no hog
transformation step. Transformations only run via `createEventSubpipeline`
(`nodejs/src/ingestion/pipelines/analytics/event-subpipeline.ts`).

So the transformation will clean up a customer's analytics numbers while their replay bill stays
exactly the same. Say that explicitly rather than letting them find out on the next invoice.

## Measuring how much replay usage is bots

Quantify before recommending changes — it separates "bots are 40% of my recordings" from
"bots are a rounding error and something else is driving the bill".

Resolve each recorded session to a user agent actually observed on it, then classify:

```sql
SELECT
    getTrafficCategory(ua) AS category,
    count() AS recorded_sessions,
    round(100.0 * count() / sum(count()) OVER (), 2) AS pct
FROM (
    SELECT
        $session_id AS session_id,
        anyIf(
            coalesce(nullIf(properties.$raw_user_agent, ''), properties.$user_agent),
            notEmpty(coalesce(nullIf(properties.$raw_user_agent, ''), properties.$user_agent))
        ) AS ua
    FROM events
    WHERE timestamp >= now() - INTERVAL 7 DAY
        AND notEmpty($session_id)
    GROUP BY session_id
    HAVING notEmpty(ua)
)
WHERE session_id IN (
    SELECT session_id
    FROM raw_session_replay_events
    WHERE min_first_timestamp >= now() - INTERVAL 7 DAY
)
GROUP BY category
ORDER BY recorded_sessions DESC
```

**Do not skip the per-session UA aggregation.** Classifying each event's UA directly and counting
distinct sessions inflates the bot share enormously, because plenty of events on a perfectly human
session carry no user agent at all, and HogQL treats an empty UA as `Automation` / `no_user_agent`.
On a real project this difference was roughly 34% "automation" the naive way versus under 1% actual
bots once sessions were resolved to a UA they genuinely presented. The `HAVING notEmpty(ua)`
and `anyIf(...)` are what make the number trustworthy.

Swap `getTrafficCategory` for `getBotName` or `getBotOperator` to name the offenders, which is
usually what tells the customer whether they are looking at ad-click fraud, AI crawlers, or their
own monitoring.

## Levers that actually reduce recorded bot sessions

Only the first is bot-aware. The rest are engagement proxies that happen to catch bots because bots
tend not to behave like people — worth setting, but be honest that they are indirect.

| Lever                                                                | Where                     | Bot-aware | Notes                                                                                                                                                   |
| -------------------------------------------------------------------- | ------------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `custom_blocked_useragents`                                          | SDK init                  | Yes       | Extends the default blocklist. The one precise tool available, and it is not discoverable in the UI — surface it. Useless against a spoofed browser UA. |
| Sampling (`session_recording_sample_rate`)                           | Settings → Session replay | No        | Cuts bot and human recordings alike, proportionally. Blunt but immediate.                                                                               |
| Minimum duration (`session_recording_minimum_duration_milliseconds`) | Settings → Session replay | No        | Catches the drive-by pattern well: many ad-click bots load once and leave. Max 30000 ms.                                                                |
| URL blocklist / URL + event triggers                                 | Settings → Session replay | No        | Record only URLs or post-interaction events real users reach. Effective when bot traffic lands on a known set of ad landing pages.                      |
| Billing limits                                                       | Organization → Billing    | No        | Caps the damage; does not choose _which_ recordings you keep. Set this first when someone is actively bleeding money.                                   |

Recommend `custom_blocked_useragents` plus minimum duration plus a billing limit as the standard
opening move, then measure again.

## Finding bot recordings in the product

`$virt_is_bot` and friends are **event** properties, and the recordings list filters sessions via a
subquery over `events`, so they work as replay filters today:

```json
{ "key": "$virt_is_bot", "value": ["true"], "operator": "exact", "type": "event" }
```

Semantics match any other event-property replay filter — it selects sessions containing at least one
matching event.

In the filter-builder UI these properties are hidden unless the
`traffic-type-virtual-properties` feature flag is enabled
(`frontend/src/lib/components/TaxonomicFilter/utils/buildTaxonomicGroups.tsx`). Without the flag,
use a raw HogQL replay filter (`properties.$virt_is_bot = true`), which is unaffected by that
exclusion, or pass `properties` through the API.

## What does not exist yet — do not promise it

- **No server-side bot toggle for replay.** `Team` has no bot-related recording field
  (`posthog/models/team/team.py`) and `remote_config` emits no bot key
  (`posthog/models/remote_config.py`), so bot filtering cannot be changed without an SDK config
  change and redeploy.
- **The usage meters do not exclude bots.** `get_teams_with_recording_count_in_period` and
  `get_teams_with_recording_bytes_in_period` (`posthog/tasks/usage_report.py`) filter only on
  timestamp and delete state, and they feed both billing and quota limiting
  (`ee/billing/quota_limiting.py`). A bot recording that got captured is a billed recording.
- **Server-side bot detection is not applied to replay ingestion.** The richer classification behind
  `isLikelyBot` in HogQL (`products/web_analytics/backend/hogql_queries/bot_definitions.py`) is
  query-time only.

If a customer needs a guarantee rather than a mitigation, the honest answer is that today it is
SDK-side blocking plus the engagement levers above, and that credits already spent are a billing
conversation, not a settings change.
