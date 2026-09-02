---
name: creating-replay-vision-scanners
description: "Guides agents through creating and safely sizing a Replay Vision scanner: choosing the scanner type (monitor/classifier/scorer/summarizer), shaping the RecordingsQuery that selects sessions, and — crucially — estimating the credits it will spend and checking the org's remaining budget before creating, so a broad scanner doesn't exhaust the budget on its first scheduled sweep.\nTRIGGER when: user asks to create, set up, or configure a Replay Vision scanner, OR when you are about to call vision-scanners-create, OR when widening an existing scanner's query, sampling_rate, or sampling_mode (or moving it to a pricier model) via vision-scanners-update.\nDO NOT TRIGGER when: only reading scanners or observations, deleting a scanner, or running an existing scanner against a single session on demand (vision-scanners-scan-session). For a one-off question about sessions you already have, use vision-scanners-inline-scan-create rather than creating a scanner — the skill's first section covers when that applies."
---

# Creating Replay Vision scanners

A scanner is a standing LLM probe over session recordings. Once created and enabled, it runs on a
**Temporal schedule that sweeps every 5 minutes**, applying its prompt to each new matching recording and
recording the result as an observation (a queryable `$recording_observed` event). Each observation spends
**credits** (1 credit = $0.01) from the org's budget for the current billing period, and an observation's
price depends on the scanner's `model` — so budget in credits, not in observation counts.

That schedule is exactly why creation needs a gut-check: a scanner with a permissive query and full sampling
starts spending automatically and can drain the whole period's budget within its first few sweeps.
Creation itself does **not** check quota — that protection only kicks in at observation time, by which point
the budget may already be gone.

## First: is a scanner even the right thing?

A scanner is a **standing watch over future recordings**. If the user has specific sessions in front of them
and a question about those sessions, they don't want a scanner at all — they want `vision-scanners-inline-scan-create`,
which takes `session_ids` plus a `prompt`, saves nothing, and schedules nothing.

Use an inline scan when the sessions are already known: "what went wrong in these five recordings", "did any
of yesterday's checkout sessions hit the coupon bug", anything you'd otherwise answer by creating a scanner
and deleting it afterwards. It costs the same credits per session and reuses answers when the same question
is asked twice, so re-asking is cheap.

Create a scanner only when the user wants recordings that **haven't happened yet** to be scanned automatically.
If you find yourself planning to create a scanner, read its results once, and delete it, stop and run an
inline scan instead — a throwaway scanner leaves a scheduled sweep running against every future recording that
matches its query.

## Core principle: size before you ship

Never create an enabled scanner blind. Estimate its monthly credit spend, check the remaining credit budget,
and — when the projected spend is a meaningful fraction of what's left — show the user the numbers and get
confirmation before creating. This is the heart of the skill; the rest is supporting detail.

## The flow

### Step 1: What should the scanner do?

Pick a `scanner_type` and write its `scanner_config`. Every type needs a `prompt`; the rest is type-specific:

| Type         | What it produces                                                  | `scanner_config` shape                                                                                                                                                      |
| ------------ | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `monitor`    | Open-ended observation against a prompt (e.g. "flag rage clicks") | `{"prompt": "..."}`; optional `"allow_inconclusive": true` (off by default, so the model must answer yes or no)                                                             |
| `classifier` | Assigns tags from a fixed label set                               | `{"prompt": "...", "tags": ["tag-a", "tag-b"]}` — `tags` needs ≥1 entry; optional `"multi_label": false` (defaults to true), `"allow_freeform_tags": true` (off by default) |
| `scorer`     | Numeric score on a rubric                                         | `{"prompt": "...", "scale": {"min": 1, "max": 5, "label": "frustration"}}` — `min` < `max`; `label` optional                                                                |
| `summarizer` | Free-text summary, plus facet embeddings for search               | `{"prompt": "..."}`; optional `"length": "short" \| "medium" \| "long"` (default `"medium"`). Embeddings are always on                                                      |

`scanner_type` is **locked after creation** — to change it you delete and recreate, so confirm the type is
right up front, and get the `scanner_config` shape right (a wrong shape is a create error, not a silent
default — unknown keys are rejected too).

If the user's intent makes the type and prompt obvious, just proceed — don't interrogate them.

### Step 2: Which sessions?

The `query` is a `RecordingsQuery` shape that selects which recordings the scanner watches. `date_from` and
`date_to` are **ignored** (the schedule controls time), so don't bother setting them. Narrow the query to the
sessions that actually matter — by event, URL, person property, duration, etc. A narrow query is the single
biggest lever on cost.

When the target is one experiment's exposed population, that's its own job — use the
`scanning-experiments-with-replay-vision` skill, which derives this query from the experiment's exposure
criteria instead of hand-building it.

Two levers narrow it further, applied in this order:

- `sampling_mode` (default `comprehensive`) is a quality pre-filter on the matched sessions: `focused` keeps
  only the top sessions by surfacing score, `balanced` drops the lowest-quality ones, `comprehensive` keeps
  everything. Use it to spend the budget on sessions worth watching rather than shrinking coverage at random.
- `sampling_rate` (0..1, default 1.0) is a random downsample applied after that. Lower it to trade coverage
  for budget. Exactly 0 pauses scanning; non-zero rates below 0.0001 are rejected.

#### Which model?

`model` sets the price of every observation the scanner makes, so it's a cost lever as much as a quality one:
`gemini-3.5-flash-lite` (2 credits), `gemini-3-flash-preview` (5 credits, the default) and `gemini-3.7-flash`
(15 credits). Start at the default and only reach for `gemini-3.7-flash` when the cheaper tiers demonstrably
miss what the scanner is looking for.

### Step 3: Size it — the gut-check (do not skip)

Before creating, run both checks and reason about them together:

1. **Estimate spend** — call `vision-scanners-estimate-create` with the proposed `query`, `sampling_rate`,
   `sampling_mode` and `model`. It returns `matched_sessions_in_window`, the `window_days` measured,
   `estimated_observations_per_month`, `credits_per_observation`, `estimated_credits_per_month`, and
   `other_enabled_scanners_monthly_credits` (what the org's other enabled scanners are already projected to
   spend). When editing an existing scanner, pass its `scanner_id` so its own estimate isn't counted twice.
2. **Check budget** — call `vision-quota-retrieve` for `remaining` and `exhausted` against the org's
   `credit_limit` (credits, 1 credit = $0.01; `null` when uncapped), plus the `period_start`/`period_end`
   of the current period.

Compare credits with credits over the same horizon, the way the product UI does — `remaining` is denominated
in credits, not observations, so comparing it against `estimated_observations_per_month` understates the cost
by the model's per-observation price.
`remaining` is what's left for the rest of the current period, so prorate the monthly projection to that
window rather than comparing a full month against it:

```text
fleet_monthly    = estimated_credits_per_month + other_enabled_scanners_monthly_credits
period_days      = period_end - period_start        (in days)
days_left        = period_end - now                 (in days, floored at 0)
rest_of_period   = fleet_monthly * days_left / period_days
```

Then decide on `rest_of_period` against `remaining`:

- If it comfortably fits within `remaining`, proceed.
- If it's a large fraction of (or exceeds) `remaining`, **stop and tell the user the concrete numbers**
  (e.g. "This scanner is projected to spend ~X credits/month, about $Y; over the N days left this period
  that's ~R credits against the Z you have left."), then confirm before creating. Tightening the `query`,
  switching `sampling_mode` to `focused`, lowering `sampling_rate`, or picking a cheaper `model` are all
  ways to bring it down.
- Quote `estimated_credits_per_month` too, since it's what the scanner costs in a full period once this
  one resets. Mid-period a scanner can fit in `remaining` and still blow the next period's budget.
- If the org is already `exhausted`, say so. A new enabled scanner won't produce anything until the budget
  resets: its scheduled observations are silently skipped, and on-demand scans are rejected outright.
- If the estimate is a large fraction of `remaining` but the user still wants the scanner, offer a
  per-scanner cap: set `credit_limit` on create so this scanner can only ever spend that many credits per
  billing period. It stops scanning once the credits left can't cover another observation, then resumes
  when the period resets. Sessions it skipped while capped are not scanned later.

Confirmation here is a conversation step, not an API capability — surface the trade-off and let the user
choose. When the projected volume is clearly small relative to the budget, you don't need to ask.

### Step 4: Create

Call `vision-scanners-create`. Minimal example:

```json
{
  "name": "Rage click monitor",
  "scanner_type": "monitor",
  "scanner_config": { "prompt": "Flag sessions where the user repeatedly clicks the same element in frustration." },
  "query": { "kind": "RecordingsQuery", "events": [{ "id": "$rageclick", "type": "events" }] },
  "sampling_rate": 1.0,
  "sampling_mode": "comprehensive",
  "model": "gemini-3-flash-preview",
  "enabled": true
}
```

`name` must be unique within the team. Set `enabled: false` if the user wants to create it paused (no
schedule, no quota consumption) and turn it on later.

`emits_signals: true` is the other switch worth knowing: it augments the prompt with the Signals side mission
and pushes one signal per finding into the PostHog Signals inbox, where findings corroborate across sessions
into reports. Turn it on when the user wants the scanner to feed their inbox rather than just accumulate
observations they have to go read.

## After creation

- Show the scanner's PostHog URL from the response so the user can review it in the UI.
- Results take a few minutes to appear (rasterizing the recording to video + the LLM call are slow). Inspect
  them with `vision-scanners-observations-list` for one scanner over time, or `vision-observations-list`
  (requires `session_id`) for every scanner's findings on a single session. To dig into a recording, hand off
  to the `investigating-replay` skill.

## Updating an existing scanner

`vision-scanners-update` is a partial update — send only changed fields. **Re-run the Step 3 gut-check
whenever you widen scope or raise the price**: a broader `query`, a higher `sampling_rate`, a looser
`sampling_mode`, or a pricier `model` all raise the monthly spend just like a fresh broad scanner would.
Toggling `enabled`, tweaking the prompt, or narrowing the query don't need a re-estimate. Editing config bumps
`scanner_version`; past observations keep a snapshot of the old config.

## Gotchas

- **One observation per (scanner, session).** Re-running a scanner on a session it already observed — even a
  failed or ineligible one — is a no-op and won't produce a fresh scan. A failed observation can be retried
  from the UI (which replaces it), but there's no MCP tool for that.
- **Ineligible ≠ failed.** Observations can land `ineligible` (e.g. `too_short`, `no_recording`) — a terminal
  non-error outcome. Check `error_reason` when triaging why a scanner produced nothing.
- **Provider/model are Google/Gemini only** in the current version.
