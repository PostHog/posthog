# Spec: Ranking survey question type

Status: Draft
Owner: TBD
Related product: Surveys

## Summary

Add a new survey question type, `ranking`, that presents respondents with a list of options
and asks them to order those options by preference. Today surveys support `open`, `link`,
`rating`, `single_choice`, and `multiple_choice`. A ranking question reuses the familiar
`choices` list from the choice questions but captures the respondent's **ordering** rather
than a single selection or an unordered set.

Typical uses: "Rank these features in the order you'd like us to build them", "Order these
reasons for churn from most to least important".

## Motivation

Choice questions tell us *which* options people care about, but not *relative* priority.
Product and research teams frequently want a prioritization signal ("what should we build
first?") and today have to approximate it with several single-choice questions or an open
text box, both of which are noisy and hard to aggregate. A first-class ranking type gives a
clean ordered response and a results view that surfaces the aggregate priority order.

## Response data model

A ranking answer is an **ordered JSON array of the choice labels**, most-preferred first.

- The array mirrors how `multiple_choice` already stores its answer (a JSON array of labels),
  so the ingestion and property-key scheme need no new shape — only new semantics (order is
  meaningful, and the array should contain every non-open choice exactly once).
- Stored on the `survey sent` event under the existing keys:
  `$survey_response` (first question) or `$survey_response_<question_id>` /
  `$survey_response_<index>` — see `SurveyEventProperties` in
  `products/surveys/backend/util.py`. No new event or property scheme.

Example stored value for a 4-option ranking:

```json
["Dark mode", "Faster load times", "Mobile app", "Better search"]
```

### Open decisions on the answer shape

1. **Partial rankings.** Does the respondent have to rank every option, or can they rank a
   subset? Recommendation: require a full ranking (all options ordered) for v1 so aggregation
   is well-defined; revisit partial ranking later. If the question is `optional`, an empty
   response is allowed as today.
2. **`hasOpenChoice`.** Multiple/single choice support an "other" free-text choice. For v1,
   **disable `hasOpenChoice` for ranking** — an open slot has ambiguous ordering semantics.
3. **`shuffleOptions`.** Still meaningful and desirable — the *initial presented order* should
   be shuffleable to avoid anchoring bias. Keep it.

## Scope of work

Rendering the interactive widget lives in the SDK repos and is out of scope for the monorepo
changes; this repo covers the type definition, validation, authoring UI, results, and the
schema/codegen plumbing. The full end-to-end feature therefore spans this repo plus the SDK
repos (`posthog-js`, `posthog-ios`, `posthog-android`, `posthog-flutter`).

### 1. Shared types and schema

- `frontend/src/types.ts`
  - Add `Ranking = 'ranking'` to `SurveyQuestionType`.
  - Add `RankingSurveyQuestion extends SurveyQuestionBase` with
    `type: SurveyQuestionType.Ranking`, `choices: string[]`, `shuffleOptions?: boolean`.
  - Add it to the `SurveyQuestion` discriminated union.
  - Decide whether `RankingSurveyQuestion` folds into `ChoiceQuestionProcessedResponses` or
    gets a new `RankingQuestionProcessedResponses` variant (recommend the latter — the
    processed shape is rank-position data, not vote counts).
- Regenerate the query schema: run `hogli build:schema` after editing `types.ts` so the enum
  propagates into `frontend/src/queries/schema.json`, `posthog/schema.py`, and the
  `schema-surveys.ts` re-export.

### 2. Backend — validation and OpenAPI schema

`products/surveys/backend/api/survey.py`

- Add `SurveyRankingQuestionSchemaSerializer` (mirrors the choice serializer: `choices` with
  `min_length=2, max_length=20`, `shuffleOptions`; no `hasOpenChoice`) and add it to
  `_SurveyQuestionUnion`.
- Add `ranking` to `SurveyBaseQuestionSchemaSerializer.type` choices.
- Update the `Survey.questions` docstring in `products/surveys/backend/models.py` and the
  `SurveyResponseAnswerSerializer` `question_type` / `answer` docs to describe the ordered-list
  answer.
- `validate_questions()` already sanitizes `choices` through `_validate_and_sanitize_choices`;
  ranking flows through it automatically. Add ranking-specific rules only where they differ
  (reject `hasOpenChoice`, require ≥ 2 choices — already enforced by the length bounds).
- Regenerate frontend/MCP types: run `hogli build:openapi` after the serializer change.

### 3. Backend — response extraction and aggregation

- `posthog/hogql/functions/survey.py` + `posthog/hogql/functions/posthog.py`: ranking answers
  are array-shaped, so reuse the existing `is_multiple_choice=true` array extraction path in
  `getSurveyResponse` (it returns the raw JSON array). Mirror any change in the raw-ClickHouse
  version `get_survey_response_clickhouse_query()` in `products/surveys/backend/util.py`.
- `products/surveys/backend/responses/per_question_stats.py`: add a `ranking` branch. A flat
  `GROUP BY answer` over an ordered array does not aggregate meaningfully. Compute a per-option
  aggregate instead (see "Aggregation method" below).
- `products/surveys/backend/responses/fetch_rows.py`: parse the array-valued ranking answer
  (same gap that exists for multiple_choice) so rows expose an ordered list rather than a raw
  JSON string.

### 4. Aggregation method

Recommended v1 aggregation: **mean rank per option**, plus the count of responses.

- For each response, option at index `i` (0-based) gets rank `i + 1`.
- Aggregate = average rank across all responses; lower mean rank = more preferred.
- Present options sorted ascending by mean rank.

This is simple, interpretable, and defined for full rankings. (Borda count is equivalent up to
a linear transform for full rankings; mean rank reads more naturally in the UI.) If partial
rankings are later allowed, revisit — unranked options need a defined treatment.

### 5. Authoring UI

- `frontend/src/scenes/surveys/constants.tsx`: add entries to `SurveyQuestionLabel`,
  `QUESTION_TYPE_OPTIONS` (label + icon), `defaultSurveyFieldValues[Ranking]` (a default
  question with two starter choices), and `QUESTION_TYPE_ICON_MAP`. The wizard's
  `QuestionTypeChip` / `AddQuestionButton` consume `QUESTION_TYPE_OPTIONS`, so they pick this
  up automatically.
- `frontend/src/scenes/surveys/SurveyEditQuestionRow.tsx`: add the type to the type dropdown.
  Reuse the existing `isChoiceQuestion` choices editor block for editing the option list, but
  hide the `hasOpenChoice` control for ranking. Treat single/multiple/ranking as a
  "choices-compatible" bucket so switching between them preserves `choices` without the
  data-loss warning dialog.
- `frontend/src/scenes/surveys/questionTypeGuards.ts`: add `isRankingQuestion`, and extend
  `isChoiceQuestion` (or add a broader `hasChoices` guard) so shared choices logic applies.
- `frontend/src/scenes/surveys/surveyLogic.tsx`: extend the type-equality checks in
  `setDefaultForQuestionType` (translation cleanup, `choices` seeding) to include `Ranking`.
- Capability decisions:
  - `canQuestionSkipSubmitButton` (`frontend/src/scenes/surveys/utils.ts`): ranking should
    **not** auto-submit — it needs an explicit confirm. Leave it out.
  - `canQuestionHaveResponseBasedBranching`
    (`frontend/src/scenes/surveys/components/question-branching/utils.ts`): ranking should
    **not** support response-based branching in v1 (the permutation space is impractical).
    `next_question` / `end` branching still works.

### 6. Results UI

- `frontend/src/scenes/surveys/surveyLogic.tsx` (`processResultsForSurveyQuestions`): add a
  `case SurveyQuestionType.Ranking` with a new `processRankingQuestion` producing mean-rank
  per option.
- `frontend/src/scenes/surveys/components/question-visualizations/SurveyQuestionVisualization.tsx`:
  add a branch rendering a new `RankingQuestionViz` component — a horizontal bar chart of
  options sorted by mean rank (model it on `MultipleChoiceBarChart`). Add a matching case to
  `QuestionLoadingSkeleton`.
- `frontend/src/scenes/surveys/utils/demoDataGenerator.ts`: add a `Ranking` case so the
  empty-state demo renders.
- `frontend/src/scenes/surveys/surveyActivityDescriber.tsx`: add a describe-changes branch for
  ranking (reuse the choice-diff rendering).

### 7. Max AI authoring

`products/surveys/backend/max_tools.py` + `prompts.py`: add `"ranking"` to
`SEMANTIC_QUESTION_TYPE` and `QUESTION_TYPE_MAP`, extend the choices-required check (currently
hardcoded to single/multiple choice) to include ranking, and document the type in the system
prompt.

### 8. SDK version gating

`frontend/src/scenes/surveys/surveyVersionRequirements.ts`: add a `SURVEY_SDK_REQUIREMENTS`
entry for the ranking feature once SDKs ship support, with `sdkVersions` per SDK and
`unsupportedSdks` (with tracking issue links) for the rest. The
`surveyVersionRequirements.test.ts` test requires every SDK to be accounted for. Until an SDK
implements ranking, its entry keeps the editor from letting users ship an unsupported survey to
that SDK. Use the `/survey-sdk-audit` skill to keep this in sync.

### 9. SDK rendering (separate repos — out of scope here)

The interactive widget (drag-to-reorder or up/down controls, response capture as an ordered
label array, `shuffleOptions` on initial render) must be implemented in:
`posthog-js` (web + React Native), `posthog-ios`, `posthog-android`, `posthog-flutter`.
These are the gating work for actually shipping the feature to end users.

## Rollout plan

1. Land the monorepo changes (types, backend validation/aggregation, editor, results) behind
   the SDK-version gating so authors can build ranking questions but the version requirements
   surface which SDKs support them.
2. Implement rendering in `posthog-js` first (widest reach), release, and add its entry to
   `SURVEY_SDK_REQUIREMENTS`.
3. Follow with iOS / Android / Flutter, updating the requirements entry as each ships.

## Testing

- Backend: extend the survey serializer tests to cover ranking validation (choices bounds,
  `hasOpenChoice` rejected) and the `per_question_stats` aggregation for an ordered-array
  answer. Add a HogQL test that `getSurveyResponse` returns the ranking array.
- Frontend: `surveyLogic` results-processing test for `processRankingQuestion` (mean-rank
  ordering), and an editor test that switching a choice question to ranking preserves choices.
- Follow `/writing-tests` — each test must catch a realistic regression not already covered.

## Open questions

- Full vs. partial ranking (see answer-shape decisions). Recommend full for v1.
- Whether ranking should also be offered in the separate `ProductTourSurveyQuestionType` flow
  (`open | rating` today). Recommend no for v1.
- Whether to display a secondary "distribution of rank positions" view in results in addition
  to mean rank.
