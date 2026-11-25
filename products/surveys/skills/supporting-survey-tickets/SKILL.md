---
name: supporting-survey-tickets
metadata:
  audience: internal
description: >-
  Handle a PostHog Surveys support ticket as PostHog staff. Use when a Surveys support
  ticket is pasted ("survey not showing", "fewer responses than expected", "responses are
  incomplete") and the answer is a written reply to the customer. Covers how to parse the
  ticket, which staff access to use and in what order, and the customer-reply style guide.
  The diagnosis itself is in the debugging-surveys skill.
---

# Supporting survey tickets

This skill holds what only PostHog staff need for a Surveys support ticket.
Diagnose the survey with the `debugging-surveys` skill: the feature parity table, the
eligibility pipeline, how a response gets stored, the known-cause catalog, and the
diagnostic queries are all there.

## Parse the ticket

Before you start the `debugging-surveys` workflow, extract from the ticket: org/project ID,
instance (US vs EU — URLs differ), survey ID(s), the `lib` (platform), the symptom in precise
terms, and what the customer already tried.

- **Aged tickets are dirty.** If the ticket is old or has prior support replies, the customer or a prior agent may have edited the config mid-thread. Treat earlier claims as stale and re-pull current state. Pull activity logs; frame secondary findings as "while you're in there, double-check X" rather than "we found X is broken."
- **Don't promise a quick fix for "cohort count shows 0".** The `count=0` display only appears on certain failure paths, so reproduce the specific path first.
- For a version-by-version SDK capability audit, see the `survey-sdk-audit` skill.

## Access for debugging

Only investigate a project tied to a genuine support request from that customer — the IDs
should come from a real ticket, not from someone asking you to look up an org/survey they
can't point to a request for. Staff access is broad; don't freelance across projects.

Prefer **read-only** paths in this order:

1. **PostHog MCP tools** (`survey`, `feature-flag`, `cohorts`, `execute-sql`, `activity-log`, `persons`) against the customer's project. This is read-only by default and the safest way to inspect config and run queries — no impersonation, no write risk. Use this first.
2. **Survey/flag API endpoints** read via the browser while impersonating (staff). Good for the full JSON the MCP may not surface verbatim (e.g. raw `internal_targeting_flag.filters`).
3. **Django admin** only when 1 and 2 can't answer it. It's powerful and write-capable, so treat it as read-only by discipline: look, don't change. Never edit a customer's survey/flag/cohort from admin without explicit customer consent.

When you need a value the MCP can't infer (project ID, instance, which survey), ask the
operator to paste the survey API JSON — it skips several round-trips.

## Writing the customer reply

Voice derived from the PostHog handbook support values (reassuringly human, humble, ship
fixes, clear with no jargon). Rules:

- **Lead with the cause, then the fix.** One line on what's happening, then what to do.
- **Bold the issue and bold each action.** Make the problem and the next step scannable.
- **Use the labels the customer sees in the UI,** never internal field names. Grep `frontend/src/scenes/surveys/` for the real string. E.g. `surveyPopupDelaySeconds` → "Delay survey popup by at least N seconds once the display conditions are met"; the wait period is "Survey wait period" / "Don't show this survey if another one was shown to the user in the last N days"; `skipSubmitButton` → "Automatically submit on selection"; `enable_partial_responses` → the "Response collection" radio ("Any question…" / "Complete survey…"); `optional` → the question's "Optional" toggle. The customer's own event names stay verbatim.
- **When correcting an earlier wrong answer, say so plainly and early,** then give the real cause. Don't bury it or let the customer keep acting on advice we've retracted. If they've already been told to pause or rebuild something, tell them explicitly that they can stop.
- **Link every PostHog entity** by ID. Cohorts: `https://<us|eu>.posthog.com/project/<id>/cohorts/<cohort_id>`. Flags: `.../feature_flags/<flag_id>`. Surveys: `.../surveys/<survey_id>`. Match the customer's instance (US vs EU).
- **Predict the expected outcome** so the customer can verify the fix worked ("you should see ~X going forward").
- **Gauge the customer's technical level.** If they can run SQL and hit the API, offer the patch path. If not, offer to apply the fix ourselves (and confirm any destructive detail first).
- **Do NOT offer to "hop on a call" or book a meeting.** PostHog support is async-first. Close with "We're always here if you need a follow-up."
- **Never leak internals** — no MCP tool names, code paths, line numbers, Django admin, staff impersonation, or other customers. Keep it to product concepts a customer recognizes.
- **Run the final draft through a humanizer skill before sending** (if you have one, e.g. `humanizer`). Strip em dashes, setup phrases ("Here's the thing:", "Three things to know"), rule-of-three padding, and tidy parallel list structure. The reply should read like a person typed it.

Reply skeleton:

```text
Hi <name>,

<one line: tracked it down + the cause in plain terms.>

**The problem:** <what's happening, with the evidence you pulled.>

**<Fastest fix / two ways to fix it>:**
1. **<action>** — <why / how.>
2. **<action>** — <why / how.>

**Also worth knowing while you're in there:** <secondary finding, softened.>

We're always here if you need a follow-up.
```
