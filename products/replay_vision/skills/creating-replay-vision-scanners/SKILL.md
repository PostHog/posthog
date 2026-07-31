---
name: creating-replay-vision-scanners
description: "Guides agents through creating and safely sizing a Replay Vision scanner: choosing the scanner type (monitor/classifier/scorer/summarizer), shaping the RecordingsQuery that selects sessions, and — crucially — estimating observation volume and checking the org's monthly quota before creating, so a broad scanner doesn't exhaust the budget on its first scheduled sweep.\nTRIGGER when: user asks to create, set up, or configure a Replay Vision scanner, OR when you are about to call vision-scanners-create, OR when widening an existing scanner's query or sampling_rate via vision-scanners-update.\nDO NOT TRIGGER when: only reading scanners or observations, deleting a scanner, or running an existing scanner against a single session on demand (vision-scanners-scan-session)."
---

# Creating Replay Vision scanners

A scanner is a standing LLM probe over session recordings. Once created and enabled, it runs on a
**Temporal schedule that sweeps every 5 minutes**, applying its prompt to each new matching recording and
recording the result as an observation (a queryable `$recording_observed` event). Each observation spends
credits from a **monthly org credit budget** (1 credit = $0.01), and an observation's price depends on the
scanner's model — so budget in credits, not in observation counts.

That schedule is exactly why creation needs a gut-check: a scanner with a permissive query and full sampling
starts consuming quota automatically and can drain the whole month's budget within its first few sweeps.
Creation itself does **not** check quota — that protection only kicks in at observation time, by which point
the budget may already be gone.

## Core principle: size before you ship

Never create an enabled scanner blind. Estimate its monthly credit spend, check the remaining credit budget,
and — when the projected spend is a meaningful fraction of what's left — show the user the numbers and get
confirmation before creating. This is the heart of the skill; the rest is supporting detail.

## The flow

### Step 1: What should the scanner do?

Pick a `scanner_type` and write its `scanner_config`. Every type needs a `prompt`; the rest is type-specific:

| Type         | What it produces                                                  | `scanner_config` shape                                                                                                                  |
| ------------ | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `monitor`    | Open-ended observation against a prompt (e.g. "flag rage clicks") | `{"prompt": "..."}`                                                                                                                     |
| `classifier` | Assigns tags from a fixed label set                               | `{"prompt": "...", "tags": ["tag-a", "tag-b"]}` — `tags` needs ≥1 entry; optional `"multi_label": true`, `"allow_freeform_tags": false` |
| `scorer`     | Numeric score on a rubric                                         | `{"prompt": "...", "scale": {"min": 1, "max": 5, "label": "frustration"}}` — `min` < `max`; `label` optional                            |
| `summarizer` | Free-text summary plus facet embeddings for search                | `{"prompt": "..."}`; optional `"length": "short" \| "medium" \| "long"` (default `"medium"`)                                            |

Summarizers always emit facet embeddings; there is no option to turn that off.

`scanner_type` is **locked after creation** — to change it you delete and recreate, so confirm the type is
right up front, and get the `scanner_config` shape right (a wrong shape is a create error, not a silent
default — unknown keys are rejected too).

If the user's intent makes the type and prompt obvious, just proceed — don't interrogate them.

### Step 2: Which sessions?

The `query` is a `RecordingsQuery` shape that selects which recordings the scanner watches. `date_from` and
`date_to` are **ignored** (the schedule controls time), so don't bother setting them. Narrow the query to the
sessions that actually matter — by event, URL, person property, duration, etc. A narrow query is the single
biggest lever on cost.

`sampling_rate` (0..1, default 1.0) is a random downsample applied _after_ the query matches. Lower it to
trade coverage for budget.

### Step 3: Size it — the gut-check (do not skip)

Before creating, run both checks and reason about them together:

1. **Estimate spend** — call `vision-scanners-estimate-create` with the proposed `query`, `sampling_rate`,
   and `model`. It returns `matched_sessions_in_window`, the `window_days` measured,
   `estimated_observations_per_month`, `credits_per_observation` (the price at that model), the resulting
   `estimated_credits_per_month`, and `other_enabled_scanners_monthly_credits` (what the org's other enabled
   scanners are already projected to spend).
2. **Check budget** — call `vision-quota-retrieve` for `remaining` and `exhausted` against the org's monthly
   `credit_limit` (credits, 1 credit = $0.01; `null` when uncapped).

Compare credits against credits — `remaining` is denominated in credits, not observations, so comparing it
against `estimated_observations_per_month` understates the cost by the model's per-observation price.

Then decide:

- If `estimated_credits_per_month` plus `other_enabled_scanners_monthly_credits` comfortably fits within
  `remaining`, proceed.
- If it's a large fraction of (or exceeds) `remaining`, **stop and tell the user the concrete numbers**
  — e.g. "This scanner is projected to spend ~X credits/month (~N observations at C credits each), on top of
  ~Y credits from your other scanners; you have Z left this month." — and confirm before creating, or suggest
  tightening the `query`, lowering `sampling_rate`, or picking a cheaper `model` first.
- If the org is already `exhausted`, say so — a new enabled scanner won't produce anything until the budget
  resets, and its observations will be silently skipped.

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
  "model": "gemini-3.6-flash",
  "enabled": true
}
```

`name` must be unique within the team. Set `enabled: false` if the user wants to create it paused (no
schedule, no quota consumption) and turn it on later.

## After creation

- Show the scanner's PostHog URL from the response so the user can review it in the UI.
- Results take a few minutes to appear (rasterizing the recording to video + the LLM call are slow). Inspect
  them with `vision-scanners-observations-list` for one scanner over time, or `vision-observations-list`
  (requires `session_id`) for every scanner's findings on a single session. To dig into a recording, hand off
  to the `investigating-replay` skill.

## Updating an existing scanner

`vision-scanners-update` is a partial update — send only changed fields. **Re-run the Step 3 gut-check
whenever you widen scope**: a broader `query` or a higher `sampling_rate` raises the sweep volume just like a
fresh broad scanner would. Toggling `enabled`, tweaking the prompt, or narrowing the query don't need a
re-estimate. Editing config bumps `scanner_version`; past observations keep a snapshot of the old config.

## Gotchas

- **One observation per (scanner, session).** Re-running a scanner on a session it already observed — even a
  failed or ineligible one — is a no-op and won't produce a fresh scan.
- **Ineligible ≠ failed.** Observations can land `ineligible` (e.g. `too_short`, `no_recording`) — a terminal
  non-error outcome. Check `error_reason` when triaging why a scanner produced nothing.
- **Provider/model are Google/Gemini only** in the current version.
