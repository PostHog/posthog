# Watchlist, explore-vs-exploit, and memory

This scout's leverage is that it gets smarter every run instead of restarting cold. A busy
project has far more dashboards and insights than one short run can score, so you maintain a
**durable watchlist** in the scratchpad and split each run between **exploiting** it
(re-checking what's due) and **exploring** (adding new high-value items). This file is the
design for that ledger and the memory conventions around it.

## The scratchpad is your only persistence

The scratchpad is durable, per-team prose keyed by string. No tags, no TTLs — **the category
is the key prefix**, so a future run finds an entry with one `text=` search. Re-using a key
rewrites the entry in place (the idempotent refresh — use it to update a baseline or a
`last_checked` timestamp without creating duplicates).

### Key vocabulary

| Key prefix                                       | Holds                                                                                                                                                                                                                                                                                                      |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `watchlist:anomaly_detection:insight:<short_id>` | A curated insight to watch (the ledger row — see schema below).                                                                                                                                                                                                                                            |
| `watchlist:anomaly_detection:dashboard:<id>`     | A curated whole dashboard to sweep (when its tiles are collectively key).                                                                                                                                                                                                                                  |
| `watchlist:anomaly_detection:importance-refresh` | Memo: when the watchlist's importance ranking was last reconciled + what changed.                                                                                                                                                                                                                          |
| `baseline:anomaly_detection:insight:<short_id>`  | The learned normal: median + MAD per seasonal bucket, so scoring is cheap.                                                                                                                                                                                                                                 |
| `report:anomaly_detection:insight:<short_id>`    | Pointer to the inbox report you authored for this anomaly: `report_id` + re-escalation condition. Add a `:<series-or-direction>` suffix when one insight carries genuinely distinct concurrent anomalies (multi-series / breakdown, or an opposite-direction move) so they don't collapse onto one report. |
| `reviewer:anomaly_detection:<area>`              | A cached owner: the bare lowercase GitHub login for a dashboard / metric area.                                                                                                                                                                                                                             |
| `noise:anomaly_detection:<topic>`                | A pattern to ignore (a chronically erratic insight, a seasonal quirk).                                                                                                                                                                                                                                     |
| `addressed:anomaly_detection:<topic>`            | Team-confirmed expected (a launch/backfill) or fix shipped — skip.                                                                                                                                                                                                                                         |
| `allowlist:anomaly_detection:insight:<short_id>` | An insight to never surface (deprecated, sandbox, test).                                                                                                                                                                                                                                                   |
| `not-in-use:anomaly_detection:team{team_id}`     | Close-out memo: team isn't actively using saved analytics right now.                                                                                                                                                                                                                                       |

### Watchlist entry schema

Keep each `watchlist:` entry a compact, parseable line so the next run can read and update it
cheaply:

```text
key:     watchlist:anomaly_detection:insight:ym0K91uz
content: "Revenue over time | dashboards: go/revenue(198672) | metric: daily revenue sum |
         cadence: daily | priority: high | last_checked: 2026-06-07T12:00Z |
         next_due: 2026-06-08T12:00Z | last_status: normal (z=0.8) | added: 2026-06-05"
```

Fields: human name, the dashboard(s) it lives on, what metric you actually score, cadence
(`hourly`/`daily`), priority (`high`/`med`/`low`, from view count + business importance),
`last_checked`, `next_due`, `last_status` (normal / watch / reported with the last z), and when
you added it. `low-data` is a valid `last_status` for items you can't baseline yet.

### Baseline entry schema

```text
key:     baseline:anomaly_detection:insight:ym0K91uz
content: "daily revenue sum, same-weekday baseline over 8 weeks (computed 2026-06-07):
         Mon median ~$X MAD ~$Y; Tue median ~$X MAD ~$Y; ... weekend lower. Refresh weekly."
```

Store enough that the next run can score the latest bucket without recomputing the whole
baseline — but re-derive from fresh data periodically (≈weekly) so the baseline tracks real
drift instead of going stale.

## Explore vs exploit

Each run, budget deliberately:

- **Exploit (most of the run).** Re-check the watchlist items that are **due**: daily items
  whose `next_due` has passed (~24h cadence), hourly items past their ~1–3h cadence. Sort
  **most-overdue first** and work down until your time budget is nearly spent. Update each
  item's `last_checked` / `next_due` / `last_status` as you go. This is where anomalies are
  actually caught.
- **Explore (a slice of the run).** Add a few new high-value items so coverage tracks what
  the team currently cares about:
  - `insights-trending-retrieve` — `days=7` for durable favourites, `days=1` for what's hot
    right now. High `view_count` is the primary "the team cares" signal.
  - `recent_dashboards` (profile) + `dashboard-get` tiles — insights on recently-accessed
    dashboards are high-value by association.
  - Cross-check against the watchlist you already have; only add genuinely new items, at most
    ~2–3 per run, each with a first baseline + cadence.

**Refresh importance every few days — the watchlist is not "done" once it's big.** Discovery
isn't only adding new items; a watchlist's _membership and priorities_ go stale as the team's
focus moves. Every ~3 days, treat the importance ranking itself as the thing to re-check:

- Re-pull `insights-trending-retrieve` (`days=7`) and `recent_dashboards`, and reconcile them
  against the watchlist you already have — not just to add, but to **re-rank and prune**: bump
  the `priority` of items climbing the view counts, and **demote or retire** items whose
  dashboard is no longer accessed or whose view count has collapsed (drop them, or mark
  `priority: low` and stretch their cadence). A dashboard created last week that's now the
  most-opened one belongs on the list; one nobody has opened in a month should not keep burning
  the budget.
- A large watchlist is **not** a reason to skip this. "The watchlist is already mature" is the
  trap: it freezes coverage on whatever was important when you bootstrapped. The refresh is
  cheap — two reads plus a diff — and it is what keeps "important" meaning _currently_
  important.
- Make it actually happen: keep one `watchlist:anomaly_detection:importance-refresh` memo with a
  `last_refreshed` timestamp and a one-line note of what changed. If it's missing or more than ~3
  days old, do the refresh this run before exploiting, then reuse the key to update it in place.
  Like the weekly baseline re-derivation above, this stops the watchlist going stale — but run it
  more often, because the team's attention shifts faster than a metric's own distribution does.

**Round-robin, don't re-scan everything.** The watchlist + `next_due` timestamps are what let
successive runs cover different items instead of all repeating the same top insights every
hour. Trust the ledger: if an item was checked 20 minutes ago by a prior run, it's not due.

**Leave yourself pointers.** When you run low on budget mid-sweep, write a quick note (reuse
the run summary, or a `watchlist:` `next_due` you set to "now" on the next item) so the next
run knows where to resume. The run summary (`signals-scout-runs-list`) is the natural place to
say "checked items A–F; G–K still due next run."

## The four states (classify every candidate before reporting)

1. **Net new** — no prior report or scratchpad entry covers this metric move. → **Author** a
   report (`emit_report`) if it clears the bar (robust z ≥ ~3.5, guards passed, seasonality
   ruled out). Stash a `report:` pointer with the new `report_id`.
2. **Material update** — you already reported this insight's anomaly, but there's new evidence
   (it's still firing, escalated, spread to related insights, or correlates with a fresh
   deploy). → **Edit** the existing report (`edit_report`): `append_note` with the new evidence
   (link a fresh notebook for the new window). Don't author a second report for the same move.
3. **Already covered** — the report exists and the move is unchanged, still within the window.
   → Skip; optionally refresh the `report:` pointer's note in place.
4. **Addressed or noise** — a `noise:` / `addressed:` / `allowlist:` entry names it (chronic
   erratic insight, known launch/backfill, deprecated insight). → Skip; note in the summary.

## Worked memory examples

Good entries are future-run actionable — the next run reads them and changes behavior.

```text
key:     report:anomaly_detection:insight:SRVNODib
content: "report_id 0192f3a1-... — authored 2026-06-07 for the spike on 'LLM Costs By AI
         Product': daily sum 3.4x the 8-Saturday baseline (z=5.1), started 06-06. If still
         elevated next run, edit_report (append_note) to escalate as sustained; if back within
         baseline, leave the report and stop."
```

```text
key:     noise:anomaly_detection:insight:tQnsSMoI
content: "'Generation calls' is chronically spiky — big legit swings on model launches and
         backfills. Require z>=4.5 AND a same-day deploy/launch correlation before reporting;
         otherwise refresh baseline only."
```

```text
key:     addressed:anomaly_detection:revenue-backfill-2026-06
content: "Revenue insights show a one-off step on 2026-06-03 from a Stripe backfill, not a
         real change. Team aware. Don't report revenue-series steps dated 2026-06-03."
```

Bad entry: key `note-1`, content "revenue looked weird today" — no entity, no condition, no
category prefix, unfindable and unactionable.

## Bootstrapping a cold team (first few runs)

The very first run has no watchlist. Bootstrap it:

1. `insights-trending-retrieve` (`days=7`, `limit=15`) → the team's most-viewed insights.
2. `recent_dashboards` from the profile → the dashboards humans actually open.
3. Pick the ~5–10 highest-value of those, set a baseline + cadence for each, write their
   `watchlist:` entries.
4. Score whatever you have time for this run; the rest become due next run.

By run ~3–5 you'll have a stable watchlist and most of each run goes to fast, cheap re-checks
against stored baselines — which is the whole point.
