---
name: debugging-surveys
description: >-
  Debug, support, and build PostHog Surveys across the backend and all five SDKs
  (web/posthog-js, iOS, Android, Flutter, React Native). Use whenever a Surveys
  support ticket is pasted ("survey not showing", "fewer responses than expected",
  "responses disappeared", "survey shows on wrong platform"), when diagnosing why a
  survey does or doesn't display, or when doing survey feature work that must ship
  across SDKs. Covers the eligibility pipeline, cross-SDK feature parity, the known-cause
  catalog, read-only diagnostic queries, staff access, and the customer-reply style guide.
---

# Debugging surveys

PostHog Surveys is a no-code in-app form builder. A customer creates a survey in the
PostHog UI; it must then be evaluated and rendered by whichever SDK their app runs.
**Most "survey not showing" tickets are eligibility problems, not rendering bugs** — the
SDK correctly decided the user is not eligible, and the job is to find _which_ gate
failed and _why_.

## Repos

GitHub is the source of truth for where the code lives. When you need to read or change SDK
source, resolve a local checkout via the registry described in
[references/local-repos.md](references/local-repos.md) so a clone is found once and reused —
don't re-clone every session. First time on a machine, run `python3 scripts/repos.py init`
to auto-discover existing checkouts; thereafter `python3 scripts/repos.py ensure <repo>`
prints the path (and `--clone` clones if missing).

| Concern              | Repo                                                                        | Where to look                                                            |
| -------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Product UI + backend | this monorepo (PostHog/posthog)                                             | UI: `frontend/src/scenes/surveys/`, backend: `products/surveys/backend/` |
| Web SDK              | [PostHog/posthog-js](https://github.com/PostHog/posthog-js)                 | `packages/browser/`                                                      |
| React Native SDK     | [PostHog/posthog-js](https://github.com/PostHog/posthog-js) (same monorepo) | `packages/react-native/`                                                 |
| iOS SDK              | [PostHog/posthog-ios](https://github.com/PostHog/posthog-ios)               | survey rendering + eligibility                                           |
| Android SDK          | [PostHog/posthog-android](https://github.com/PostHog/posthog-android)       | eligibility (delegate-based UI)                                          |
| Flutter SDK          | [PostHog/posthog-flutter](https://github.com/PostHog/posthog-flutter)       | Dart rendering; native iOS/Android handles eligibility                   |
| Public docs          | [PostHog/posthog.com](https://github.com/PostHog/posthog.com)               | `contents/docs/surveys/`                                                 |

Always check the local checkout is present and on a sane branch before quoting code; line
numbers drift, so grep for the symbol rather than trusting a remembered line number.

## Cross-SDK feature parity (check this FIRST)

A large class of tickets is "customer expects a feature their platform doesn't support."
Confirm the survey's `lib` / the customer's platform before anything else, then consult
this table. Verified against the SDK source — re-verify if it's been months, the gaps
get filled over time.

| Feature                         | Web (posthog-js)                | iOS                                       | Android                            | Flutter                            | React Native                            |
| ------------------------------- | ------------------------------- | ----------------------------------------- | ---------------------------------- | ---------------------------------- | --------------------------------------- |
| Rendering                       | DOM + shadow root               | Native SwiftUI (`SurveysWindow`)          | **No built-in UI** — delegate only | Dart widgets (`SurveyBottomSheet`) | RN components (`SurveyModal`)           |
| Event-based triggers            | yes (since 1.137.0, 2024-06-05) | yes                                       | yes                                | yes (native side)                  | yes                                     |
| URL / screen targeting          | yes                             | decoded but **NOT evaluated** (`// TODO`) | decoded but **NOT evaluated**      | **NOT evaluated** (native gap)     | **explicitly excluded** in filter       |
| Feature-flag / cohort targeting | yes                             | yes                                       | yes                                | yes (native side)                  | yes                                     |
| `seenSurveyWaitPeriodInDays`    | yes                             | yes                                       | yes                                | yes (native side)                  | stored but **comparison commented out** |
| `surveyPopupDelaySeconds`       | yes                             | **not implemented**                       | **not implemented**                | **not implemented**                | **not implemented** (TODO)              |

Consequences worth memorizing:

- **`surveyPopupDelaySeconds` is web-only.** If a mobile ticket blames the delay, it's a red herring.
- **URL targeting is effectively web-only.** Mobile SDKs decode the field but never enforce it; React Native filters those surveys out entirely. A mobile survey with a URL condition behaves as "no URL condition" (mobile/flutter) or "never shows" (RN).
- **Android ships no survey UI.** The app (or the Flutter plugin) must provide a `PostHogSurveysDelegate`. "Survey never renders on Android" is often a missing delegate, not a PostHog bug.
- **Flutter is hybrid:** triggering/eligibility runs in the native iOS/Android layer; rendering is Dart (`SurveyService.showSurvey` → `showModalBottomSheet`). It does _not_ "just call native" for UI. So a Flutter rendering bug lives in Dart; a Flutter eligibility bug lives in native.
- **React Native wait period is silently disabled** (the check is commented out). Don't blame the wait period on RN.

For a deeper version-by-version capability audit, see the `survey-sdk-audit` skill if available.

## How a survey actually gets shown (the web eligibility pipeline)

The web SDK is the most complex and the most common in tickets. Mental model from
`packages/browser/src/extensions/surveys.tsx` (`checkSurveyEligibility`) — checks run in
order, first failure wins:

1. `isSurveyRunning` — has `start_date`, no `end_date`.
2. survey `type` is in-app (Popover / Widget / API).
3. `linked_flag_key` enabled (if set).
4. `targeting_flag_key` enabled (if set) — customer-defined property targeting.
5. `_internalFlagCheckSatisfied` — the auto-generated internal targeting flag.
6. `hasWaitPeriodPassed` — `seenSurveyWaitPeriodInDays` vs `localStorage.lastSeenSurveyDate`.
7. `getSurveySeen` — per-survey seen flag.

Then in `getActiveMatchingSurveys`: URL/device/selector match, event/action trigger fired, and flag re-check.

Two non-obvious facts that drive real tickets:

- **The server returns ALL non-archived surveys** (`SurveyViewSet`, `products/surveys/backend/api/survey.py`). It does **not** pre-filter by the internal targeting flag. All eligibility is client-side. So you cannot conclude "the backend excluded them" — the SDK did.
- **The wait period has TWO independent implementations.** `canActivateRepeatedly` (true when `schedule: 'always'`) short-circuits `_internalFlagCheckSatisfied` (step 5) — so `always` bypasses the internal flag, including its `$last_seen_survey_date` rule. But `hasWaitPeriodPassed` (step 6) reads `localStorage.lastSeenSurveyDate` directly and is **NOT** bypassed by `canActivateRepeatedly`. So a `schedule: 'always'` survey with `seenSurveyWaitPeriodInDays: 30` still enforces the 30-day wait via the localStorage path. `lastSeenSurveyDate` is updated whenever _any_ survey is shown, regardless of completion.

## Debugging workflow

1. **Parse the ticket.** Extract: org/project ID, instance (US vs EU — URLs differ), survey ID(s), the `lib` (platform), the symptom in precise terms, and what the customer already tried. If the ticket is aged or has prior support replies, the config may have been edited mid-thread — treat earlier claims as stale and re-pull current state.

2. **Disambiguate "none" vs "fewer."** Customers say "no responses" when they mean "fewer." Pull the `survey shown` vs `survey sent` counts before/after the suspected change (see [references/diagnostic-queries.md](references/diagnostic-queries.md)). If the _response rate_ (sent/shown) is stable, the problem is upstream eligibility (fewer people shown), not rendering or submission. This single check redirects most investigations correctly.

3. **Platform parity check.** Confirm the `lib` and consult the parity table. Eliminate features the platform doesn't support before investigating them.

4. **Pull the survey definition.** `GET /api/projects/<id>/surveys/<sid>/`. Inspect `conditions` (events, url, seenSurveyWaitPeriodInDays), `appearance.surveyPopupDelaySeconds`, `schedule`, `linked_flag`, `targeting_flag`, `internal_targeting_flag.filters`, `responses_limit`, `iteration_*`.

5. **Pull the targeting-flag activity log** for any "stopped showing" ticket. Cohort swaps and rollout changes are invisible in the current config but show up here: `GET /api/projects/<id>/activity_log/?scope=FeatureFlag&item_id=<flag_id>&limit=20`. Also `?scope=Survey&item_id=<sid>` to see whether the survey itself was edited.

6. **Confirm with events.** Use `$feature_flag_called` to see what the gating flag actually returned for affected users, and whether `$groups` is set (see group-aggregation cause below). Use `survey shown` to see real reach vs the stats UI.

7. **Diagnose against the known-cause catalog**, confirm with one targeted query, then write the reply.

## Known-cause catalog

Ordered roughly by how often they're the answer.

### "Survey shows to fewer users than expected"

- **`surveyPopupDelaySeconds` + URL re-check (web only).** After the event fires and eligibility passes, the SDK waits N seconds, then re-checks `doesSurveyUrlMatch` against the _current_ URL before rendering (`handlePopoverSurvey`). If the user navigated during the delay, the survey is silently dropped — no `survey shown`. Common on navigation-heavy apps with a non-trivial delay. Fix: lower the delay to 0–2s.
- **`seenSurveyWaitPeriodInDays` + the customer's other surveys.** Any survey shown to a user updates `lastSeenSurveyDate`; this survey is then blocked for the wait window. Completion status is irrelevant. Verify by checking whether the _unshown_ cohort saw another survey recently — and confirm against a control group (do the _shown_ users differ?). Fix: lower the wait period, or pause competing surveys.
- **Cohort composition changed.** If the survey targets a cohort and someone edited the source dynamic cohort (e.g. added a behavioral filter), every static snapshot taken afterward inherits the narrower definition. Reach drops without any survey-side change. Find it in the flag activity log (cohort swap) and confirm cohort sizes via `static_cohort_people`.

### "Event-based survey never fires"

- **Timing race at session start.** Event captured before `/api/surveys` returns and the capture hook registers. Signature: event fires very early in session. Unavoidable client-side; mitigate by triggering on a slightly later event.
- **Group-aggregated `linked_flag` with no group context.** If `linked_flag` (or targeting flag) has `aggregation_group_type_index` set, it evaluates against a _group_, not the person. Without `posthog.group(<index>, <key>)` set before the event fires, the flag returns **false** and the survey never shows. Signature: `$feature_flag_called` returns `false` with empty `$groups`, and the `$feature/<key>` property is missing from the trigger events. Fix: set group context in the SDK, or switch the survey to a person-level flag.
- **Customer wired the survey to the wrong flag.** They create a flag with email/property targeting but the survey's `linked_flag`/`targeting_flag` points at a _different_ flag. Always confirm the actual `linked_flag.key` / `targeting_flag.key` from the API — don't trust the customer's description.
- **Behavioral cohort in a realtime flag.** A cohort with `performed_event`/behavioral filters can't be evaluated in realtime flag bytecode (`"Unsupported behavioral filter for realtime bytecode"`, `posthog/api/cohort.py`). The cohort shows a `bytecode_error`. Surveys/flags can't use it directly — the customer must make a _static_ copy of the cohort and target that.

### "Responses show as zero in the UI but raw events exist"

- **Max AI corrupted the survey definition.** Max's `edit_survey` tool (`products/surveys/backend/max_tools.py`) has two failure modes: (a) on reorder/edit it rebuilds each question from `QUESTION_TYPE_MAP` (`nps`→scale 10, `csat`→scale 5, etc.), so picking the wrong semantic type silently changes a question's scale; (b) the `id` field expects 1-indexed labels (`"1"`,`"2"`) — passing a real UUID falls through and a _fresh_ UUID is generated, so responses keyed by `$survey_response_<old_uuid>` no longer join to the question. Raw events are intact; only the definition is wrong. Fix: PATCH the `questions` array back to the original UUIDs (recoverable from the response events) and restore the question type. Tell the customer to edit question _text_ via the UI, and avoid asking Max to reorder questions on a survey with historical responses until the tool guards UUIDs.

### "Cohort count shows 0 but the cohort is populated"

- Cosmetic UI bug, does **not** affect targeting. Confirm the real count via `static_cohort_people`. NOTE: this is _not_ a simple one-line bug — the normal `insert_cohort_from_query` path does recompute count via `count_cohort_members`; the `count=0` display only appears on certain failure paths. Do not promise a quick fix without reproducing the specific path.

### General caution

- **Aged tickets are dirty.** Config may have been edited by the customer or a prior agent during troubleshooting. Pull activity logs; frame secondary findings as "while you're in there, double-check X" rather than "we found X is broken."
- **The stats UI can undercount vs raw `survey shown` events.** If the numbers don't reconcile, trust the raw events and flag the discrepancy as a separate follow-up.

## Diagnostic queries

Read-only HogQL templates for the disambiguators and confirmations above live in
[references/diagnostic-queries.md](references/diagnostic-queries.md). Run them via the
PostHog MCP `execute-sql` against the customer's project.

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
- **Use the labels the customer sees in the UI,** never internal field names. Grep `frontend/src/scenes/surveys/` for the real string. E.g. `surveyPopupDelaySeconds` → "Delay survey popup by at least N seconds once the display conditions are met"; the wait period is "Survey wait period" / "Don't show this survey if another one was shown to the user in the last N days". The customer's own event names stay verbatim.
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

## Feature work — shipping across SDKs

A survey capability is only "done" when it works (or is deliberately scoped out) on every
SDK a customer might use. When building or changing survey behavior:

1. Land the backend/UI change in this repo (serializer + `frontend/src/scenes/surveys/`).
2. Decide the per-SDK story using the parity table. If a feature lands web-only (like
   `surveyPopupDelaySeconds`), say so explicitly in the docs and the PR — silent gaps
   become support tickets.
3. Implement in the SDK repos (`posthog-js` covers both web and React Native), then
   `posthog-ios`, `posthog-android`, and the Flutter Dart layer. Remember Flutter's split:
   eligibility/trigger logic is native (iOS/Android), rendering is Dart. Use the registry
   in [references/local-repos.md](references/local-repos.md) to find each checkout.
4. Update the `posthog.com` docs (`contents/docs/surveys/`) and this parity table.
5. Use the `survey-sdk-audit` skill (if available) to confirm version requirements and cross-SDK coverage.
