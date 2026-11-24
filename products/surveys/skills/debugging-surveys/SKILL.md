---
name: debugging-surveys
description: >-
  Diagnose PostHog Surveys configuration and responses across all five SDKs
  (web/posthog-js, iOS, Android, Flutter, React Native). Use when a survey misbehaves
  ("survey not showing", "fewer responses than expected", "responses disappeared",
  "responses are incomplete", "only the first question was answered", "the user says they
  didn't mean to submit", "survey shows on wrong platform"), or when diagnosing why a survey
  does or doesn't display. Covers the eligibility pipeline, how a response actually gets
  stored (partial responses, branching, optional questions, auto-submit), cross-SDK feature
  parity, the known-cause catalog, and read-only diagnostic queries.
---

# Debugging surveys

PostHog Surveys is a no-code in-app form builder. A survey is created in the
PostHog UI; it must then be evaluated and rendered by whichever SDK the app runs.
**Most "survey not showing" reports are eligibility problems, not rendering bugs** — the
SDK correctly decided the user is not eligible, and the job is to find _which_ gate
failed and _why_.

## Access requirements

Use PostHog MCP tools or the survey API to inspect survey configuration and responses.
A checkout of the PostHog repository is not required for these diagnostic steps.

## Cross-SDK feature parity (check this FIRST)

A common cause is expecting a feature that the app's platform doesn't support.
Confirm the survey's `lib` / the app's platform before anything else, then consult
this table. Verified against the SDK source — re-verify if it's been months, the gaps
get filled over time.

| Feature                          | Web (posthog-js)                | iOS                                       | Android                            | Flutter                            | React Native                      |
| -------------------------------- | ------------------------------- | ----------------------------------------- | ---------------------------------- | ---------------------------------- | --------------------------------- |
| Rendering                        | DOM + shadow root               | Native SwiftUI (`SurveysWindow`)          | **No built-in UI** — delegate only | Dart widgets (`SurveyBottomSheet`) | RN components (`SurveyModal`)     |
| Event-based triggers             | yes (since 1.137.0, 2024-06-05) | yes                                       | yes                                | yes (native side)                  | yes                               |
| URL / screen targeting           | yes                             | decoded but **NOT evaluated** (`// TODO`) | decoded but **NOT evaluated**      | **NOT evaluated** (native gap)     | **explicitly excluded** in filter |
| Feature-flag / cohort targeting  | yes                             | yes                                       | yes                                | yes (native side)                  | yes                               |
| `seenSurveyWaitPeriodInDays`     | yes                             | yes                                       | yes                                | yes (native side)                  | yes (≥ 4.81.5)                    |
| `surveyPopupDelaySeconds`        | yes                             | **not implemented**                       | **not implemented**                | **not implemented**                | **not implemented** (TODO)        |
| `enable_partial_responses`       | yes (≥ 1.240.0)                 | **no**                                    | **no**                             | **no**                             | **no**                            |
| `skipSubmitButton` (auto-submit) | yes (≥ 1.244.0)                 | **no**                                    | **no**                             | **no**                             | **no**                            |

The last two rows are per the editor's own help text ("Doesn't work with the mobile SDKs for
now" / "Not available for the mobile SDKs at the moment") rather than a per-SDK source audit.

Consequences worth memorizing:

- **`surveyPopupDelaySeconds` is web-only.** If a report about a mobile app blames the delay, it's a red herring.
- **Partial responses and auto-submit are web-only too.** On mobile a survey always stores one response at the end, and a rating tap never self-submits. Don't carry a web diagnosis onto a mobile app.
- **URL targeting is effectively web-only.** Mobile SDKs decode the field but never enforce it; React Native filters those surveys out entirely. A mobile survey with a URL condition behaves as "no URL condition" (mobile/flutter) or "never shows" (RN).
- **Android ships no survey UI.** The app (or the Flutter plugin) must provide a `PostHogSurveysDelegate`. "Survey never renders on Android" is often a missing delegate, not a PostHog bug.
- **Flutter is hybrid:** triggering/eligibility runs in the native iOS/Android layer; rendering is Dart (`SurveyService.showSurvey` → `showModalBottomSheet`). It does _not_ "just call native" for UI. So a Flutter rendering bug lives in Dart; a Flutter eligibility bug lives in native.
- **React Native enforces the wait period from 4.81.5.** Older versions skip the check, so on those versions don't blame the wait period.

## How a survey actually gets shown (the web eligibility pipeline)

The web SDK is the most complex and the most common source of reports. Mental model from
`packages/browser/src/extensions/surveys.tsx` (`checkSurveyEligibility`) — checks run in
order, first failure wins:

1. `isSurveyRunning` — has `start_date`, no `end_date`.
2. survey `type` is in-app (Popover / Widget / API).
3. `linked_flag_key` enabled (if set).
4. `targeting_flag_key` enabled (if set) — user-defined property targeting.
5. `_internalFlagCheckSatisfied` — the auto-generated internal targeting flag.
6. `hasWaitPeriodPassed` — `seenSurveyWaitPeriodInDays` vs `localStorage.lastSeenSurveyDate`.
7. `getSurveySeen` — per-survey seen flag.

Then in `getActiveMatchingSurveys`: URL/device/selector match, event/action trigger fired, and flag re-check.

Two non-obvious facts that explain many reports:

- **The server returns ALL non-archived surveys** (`SurveyViewSet`, `products/surveys/backend/api/survey.py`). It does **not** pre-filter by the internal targeting flag. All eligibility is client-side. So you cannot conclude "the backend excluded them" — the SDK did.
- **The wait period has TWO independent implementations.** `canActivateRepeatedly` (true when `schedule: 'always'`) short-circuits `_internalFlagCheckSatisfied` (step 5) — so `always` bypasses the internal flag, including its `$survey_last_seen_date` rule. But `hasWaitPeriodPassed` (step 6) reads `localStorage.lastSeenSurveyDate` directly and is **NOT** bypassed by `canActivateRepeatedly`. So a `schedule: 'always'` survey with `seenSurveyWaitPeriodInDays: 30` still enforces the 30-day wait via the localStorage path. `lastSeenSurveyDate` is updated whenever _any_ survey is shown, regardless of completion. The same short-circuit also drops the internal flag's `$survey_responded/<id> is_not_set` rule, so **`schedule: 'always'` lets one person respond repeatedly** — check `uniq(distinct_id)` against `count()` on `survey sent` before reading a response count as a respondent count.

## How a response actually gets stored

Showing a survey and storing a response are separate pipelines. "Wrong data" reports are about the
second one, and its UI copy is genuinely misleading — reason from the code, not from the label.

### "Response collection" maps to `enable_partial_responses`

The radio in `frontend/src/scenes/surveys/SurveyResponsesCollection.tsx`. "Any question: when at
least one question is answered…" is `true`; "Complete survey: the response is stored when all
questions are answered" is `false`.

- `true` -> `sendSurveyEvent` fires on **every** `onNextButtonClick`, so one `survey sent` per
  question answered, all sharing a `$survey_submission_id` with `$survey_completed` running
  `false ... true`.
- `false` -> one `survey sent` event, at the end of the path.

The setting controls capture, not response visibility. The results include every `survey sent`
and every `survey dismissed` or `survey abandoned` marked `$survey_partially_completed = true`.
`buildMergedSubmissionsSubquery` in `frontend/src/scenes/surveys/utils.ts` merges the latest
answer per question for each submission ID; events without an ID stay separate. **Raw event
counts can exceed response counts.** A completed event takes precedence over earlier partial
closures. Otherwise the outcome chip reads "Dismissed" when the latest response event is a
dismissal, and "Abandoned" for other unfinished submissions. "Abandoned" does not prove a
page-unload event or inactivity timeout occurred; a later completion updates the same row.

**The defaults disagree by creation path:** `NEW_SURVEY` sets `true`
(`frontend/src/scenes/surveys/constants.tsx`) but the Django model default is `False`
(`products/surveys/backend/models.py`). Read it, don't infer it from the creation date.

### "All questions answered" does not mean what it says

`isSurveyCompleted` is `getNextSurveyStep(...) === End` — **the respondent reached the end of their
own branching path.** Nothing checks that every question holds a value, and two things then blank
out cells on a complete response: questions **skipped by branching have no key at all**
(`onNextButtonClick` prunes to `visitedIndices` before capture, so absent rather than `""` or
`null`), and **`optional: true` questions clicked past are stored as `null`**
(`submitDisabled` is `isNull(rating) && !question.optional`).

So on a branching survey with optional tail questions, "only the first question was answered" is
the **expected shape of a complete response**. Blank ≠ unanswered. Check `branching` and `optional`
on every question before believing a bug.

### Branching is in the API — read it, don't ask for it

It's `questions[].branching`, returned verbatim by both the management API and the SDK payload, in
four shapes: `next_question`, `end` (the confirmation message), `specific_question` + `index`, and
`response_based` + `responseValues`. Two traps: for **rating** questions `responseValues` is keyed
by _bucket_ (`negative`/`neutral`/`positive`, or NPS `detractors`/`passives`/`promoters`), not by
value; and a bucket **missing** from `responseValues` silently falls through to
`currentQuestionIndex + 1`. So `{negative: 3, neutral: 3}` on a 5-scale is a complete, working
config that reads like an omission. Bucket boundaries per scale are in
[references/reading-responses.md](references/reading-responses.md) — don't guess them, scale 2 is
inverted.

### The event vocabulary

`survey shown` (fired inside `showSurvey()` at the moment the popup becomes visible, i.e. **after**
`surveyPopupDelaySeconds`, so shown→sent latency is real time-on-popup), `survey sent`,
`survey dismissed` (explicit close), `survey abandoned` (`handlePageUnload` →
`sendSurveyAbandonedEvent`). `$survey_partially_completed` appears on `dismissed` and `abandoned`
only, never on `sent`. All of them carry `sessionRecordingUrl`, so a disputed submission can often
be **watched** instead of theorized about. A populated URL only proves a session id was captured,
not that a recording exists: replay is off by default, and the default cloud retention of 30 days is
well short of these queries' 180-day window. Open the link before offering it as evidence.

### Read answers with `getSurveyResponse`, never a guessed key

**`getSurveyResponse(<index>, '<questionId>')`** is the HogQL helper the product itself reads
answers with (`posthog/hogql/functions/survey.py`, used across
`products/surveys/backend/responses/`). Prefer it over hand-writing a property key: response keys
come in three formats, and the helper coalesces the current UUID-keyed one
(`$survey_response_<questionId>`) with the legacy index-keyed one, so it returns what the
results table in PostHog shows. Pass `true` as a third argument for multiple-choice questions. A
hand-written `properties.$survey_response_<uuid>` misses legacy-keyed answers, and inside a
`countIf` that silently converts a real answer into "unanswered" and inflates the incomplete ratio.

Whichever you use, **the index and id must come from `questions[]` in the survey JSON.** Guessing
which UUID belongs to which question is the fastest route to a wrong conclusion: it reads one
question's answers under another's label, and the resulting ratio looks like a serious bug. If you
have no survey JSON, unroll `$survey_questions`, which carries the question text alongside the
answer. Formats and templates: [references/reading-responses.md](references/reading-responses.md),
[references/diagnostic-queries.md](references/diagnostic-queries.md).

**Sanity check the mapping before trusting the numbers:** if a column you labeled as a
single-choice question contains free text, the mapping is wrong.

## Debugging workflow

1. **Pin down the report.** Establish the survey ID(s), the `lib` (platform), the symptom in precise terms, and what was already tried. The config may have been edited since the problem was first seen, so pull the current state instead of trusting an earlier description.

2. **Disambiguate "none" vs "fewer."** People say "no responses" when they mean "fewer." Pull the `survey shown` vs `survey sent` counts before/after the suspected change (see [references/diagnostic-queries.md](references/diagnostic-queries.md)). If the _response rate_ (sent/shown) is stable, the problem is upstream eligibility (fewer people shown), not rendering or submission. This single check redirects most investigations correctly.

2b. **For a data-quality report, disambiguate "incomplete" vs "complete but sparse."** Before anything else, check whether the blank cells are questions the respondent was never asked. Branching plus optional questions makes a complete response look abandoned, and this is the single most common reason a survey gets reported as broken when it isn't. See [How a response actually gets stored](#how-a-response-actually-gets-stored).

3. **Platform parity check.** Confirm the `lib` and consult the parity table. Eliminate features the platform doesn't support before investigating them.

4. **Pull the survey definition.** `GET /api/projects/<id>/surveys/<sid>/`. Inspect `conditions` (events, url, seenSurveyWaitPeriodInDays, repeatedActivation), `appearance.surveyPopupDelaySeconds`, `appearance.position`, `schedule`, `linked_flag`, `targeting_flag`, `internal_targeting_flag.filters`, `responses_limit`, `iteration_*`, `enable_partial_responses` — and then go **inside each question**: `id`, `type`, `scale`, `optional`, `skipSubmitButton`, `branching`. The per-question fields answer most "wrong data" reports on their own and are easy to miss, since a shallow look at top-level keys doesn't surface them.

5. **Pull the targeting-flag activity log** for any "stopped showing" report. Cohort swaps and rollout changes are invisible in the current config but show up here: `GET /api/projects/<id>/activity_log/?scope=FeatureFlag&item_id=<flag_id>&limit=20`. Also `?scope=Survey&item_id=<sid>` to see whether the survey itself was edited.

6. **Confirm with events.** Use `$feature_flag_called` to see what the gating flag actually returned for affected users, and whether `$groups` is set (see group-aggregation cause below). Use `survey shown` to see real reach vs the stats UI.

7. **Diagnose against the known-cause catalog**, confirm with one targeted query, then report the cause and the fix.

## Before you call it an SDK bug

These reports attract a specific failure mode: the symptom looks impossible, so the SDK gets blamed
and the advice becomes to pause the survey, file a bug, and rebuild the questions. That advice
is expensive and hard to walk back — restructuring destroys the comparability of every response
already collected, and reordering questions risks the UUID problem below. Clear all four gates
before writing "this is a bug":

1. **Read the survey JSON**, per-question `branching`, `optional`, `skipSubmitButton` and `scale` included. Most "impossible" behavior is configured behavior.
2. **Reproduce it in Preview.**
3. **Read the SDK source for the handler you're accusing.** Grep the symbol; don't reason from what a setting is named. `enable_partial_responses` and "all questions answered" both mean something narrower than they sound.
4. **Re-check your own query before trusting a shocking ratio.** "89% of responses are incomplete" is more often a bad response-key mapping than a real defect.

If it survives all four it's a bug: name the file and handler, and file it upstream.

## Known-cause catalog

Ordered roughly by how often they're the answer.

### "Survey shows to fewer users than expected"

- **`surveyPopupDelaySeconds` + URL re-check (web only).** After the event fires and eligibility passes, the SDK waits N seconds, then re-checks `doesSurveyUrlMatch` against the _current_ URL before rendering (`handlePopoverSurvey`). If the user navigated during the delay, the survey is silently dropped — no `survey shown`. Common on navigation-heavy apps with a non-trivial delay. Fix: lower the delay to 0–2s.
- **`seenSurveyWaitPeriodInDays` + the project's other surveys.** Any survey shown to a user updates `lastSeenSurveyDate`; this survey is then blocked for the wait window. Completion status is irrelevant. Verify by checking whether the _unshown_ cohort saw another survey recently — and confirm against a control group (do the _shown_ users differ?). Fix: lower the wait period, or pause competing surveys.
- **Cohort composition changed.** If the survey targets a cohort and someone edited the source dynamic cohort (e.g. added a behavioral filter), every static snapshot taken afterward inherits the narrower definition. Reach drops without any survey-side change. Find it in the flag activity log (cohort swap) and confirm cohort sizes via `static_cohort_people`.

### "Event-based survey never fires"

- **Timing race at session start.** Event captured before `/api/surveys` returns and the capture hook registers. Signature: event fires very early in session. Unavoidable client-side; mitigate by triggering on a slightly later event.
- **Group-aggregated `linked_flag` with no group context.** If `linked_flag` (or targeting flag) has `aggregation_group_type_index` set, it evaluates against a _group_, not the person. Without `posthog.group(<index>, <key>)` set before the event fires, the flag returns **false** and the survey never shows. Signature: `$feature_flag_called` returns `false` with empty `$groups`, and the `$feature/<key>` property is missing from the trigger events. Fix: set group context in the SDK, or switch the survey to a person-level flag.
- **The survey is wired to the wrong flag.** A flag with email/property targeting exists, but the survey's `linked_flag`/`targeting_flag` points at a _different_ flag. Always confirm the actual `linked_flag.key` / `targeting_flag.key` from the API — don't trust a description of the setup.
- **Behavioral cohort in a realtime flag.** A cohort with `performed_event`/behavioral filters can't be evaluated in realtime flag bytecode (`"Unsupported behavioral filter for realtime bytecode"`, `posthog/api/cohort.py`). The cohort shows a `bytecode_error`. Surveys/flags can't use it directly — make a _static_ copy of the cohort and target that.

### "Responses are incomplete — only the first question has a value"

Usually not a bug — see [How a response actually gets stored](#how-a-response-actually-gets-stored). Work these four first; only then is the completion condition genuinely not being honored.

- **Branching skipped the blank questions.** Map it from `questions[].branching` yourself. A description of the intended branching may not be what's saved, and a rating bucket absent from `responseValues` falls through to the next index.
- **The blank questions are `optional: true`** and the respondent clicked past them. A rating plus two skipped optional open-text questions is a _complete_ submission with one value in it.
- **Partial responses is on** and you're reading intermediate events in raw SQL that the UI collapses by `$survey_submission_id`.
- **The response keys were guessed.** Re-run keyed off `questions[].id`.

### "The respondent says they didn't mean to submit"

- **`skipSubmitButton`, shown in the editor as "Automatically submit on selection".** When true no submit button renders at all (`BottomSection.tsx`) and one click both records the answer and advances — `setRating(response)` then `handleSubmit(response)` → `onNextButtonClick` in the same handler invocation, no debounce, no confirm. Rating and single-choice-without-open-choice only (`canQuestionSkipSubmitButton`); web-only. It is **on by default in every survey template** (`constants.tsx`) and in quick-create, so people rarely know they enabled it.
- **It compounds with popup placement.** `appearance.position: middle_center`, a large `maxWidth`, and a non-zero `surveyPopupDelaySeconds` mean the popup materializes seconds after the trigger under a cursor that's still moving, and the next click lands on an answer. Consecutive auto-submitting questions let someone click through most of a survey without reading it.
- **Diagnose with shown→sent latency,** then confirm from the replay (`sessionRecordingUrl` on `survey sent`). A cluster of sub-10-second completions on a multi-question survey is the signature; genuine respondents take longer and leave text behind. Fix is to uncheck the setting — **not** to move the question, since the behavior follows the question wherever it sits.

### "Responses show as zero in the UI but raw events exist"

- **Max AI corrupted the survey definition.** Max's `edit_survey` tool (`products/surveys/backend/max_tools.py`) has two failure modes: (a) on reorder/edit it rebuilds each question from `QUESTION_TYPE_MAP` (`nps`→scale 10, `csat`→scale 5, etc.), so picking the wrong semantic type silently changes a question's scale; (b) the `id` field expects 1-indexed labels (`"1"`,`"2"`) — passing a real UUID falls through and a _fresh_ UUID is generated, so responses keyed by `$survey_response_<old_uuid>` no longer join to the question. Raw events are intact; only the definition is wrong. Fix: PATCH the `questions` array back to the original UUIDs (recoverable from the response events) and restore the question type. Edit question _text_ via the UI, and avoid asking Max to reorder questions on a survey with historical responses until the tool guards UUIDs.

### "Cohort count shows 0 but the cohort is populated"

- Cosmetic UI bug, does **not** affect targeting. Confirm the real count via `static_cohort_people`. The normal `insert_cohort_from_query` path does recompute count via `count_cohort_members`; the `count=0` display only appears on certain failure paths.

### General caution

- **The stats UI can undercount vs raw `survey shown` events.** If the numbers don't reconcile, trust the raw events and flag the discrepancy as a separate follow-up.
- **Check both `$email` and `email` on the person.** `person.properties.$email` is what the SDKs set; plenty of projects also set a bare `email`. Querying one and concluding "this user was never identified" is a common miss — use `coalesce(person.properties.$email, person.properties.email)`.

## Diagnostic queries

Read-only HogQL templates for the disambiguators and confirmations above live in
[references/diagnostic-queries.md](references/diagnostic-queries.md). Run them via the
PostHog MCP `execute-sql` against the project.
