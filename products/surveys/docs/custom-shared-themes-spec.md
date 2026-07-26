# Feature spec: custom shared survey themes

## Summary

Let people save the survey appearance they just customized as a named, reusable **theme**
that is shared across everyone in the workspace. After tweaking colors, fonts, radius,
and layout in the survey editor's **Customization** panel, a "Save as theme" action captures
that look, names it, and stores it at the project level. From then on the theme shows up in
the theme picker for every survey in the project, next to the six built-in presets, so anyone
can start a new survey from the workspace's own house style with one click.

## Why

Teams that care about survey styling re-create the same palette on every survey by hand, or
paste hex codes between surveys. There's a single project-wide default appearance today, but
no way to keep more than one saved look (e.g. one for NPS popovers, one for a dark widget) or
to save a look you built inside the editor without leaving for project settings. This closes
that gap: build it once in the editor, name it, and it's available to the whole workspace.

## Today's building blocks (what already exists)

Grounding the design in the current code so the new feature slots in cleanly rather than
reinventing pieces.

- **Per-survey appearance.** `Survey.appearance` is a `JSONField`
  (`products/surveys/backend/models.py`). Its shape is the `SurveyAppearance` TS type
  (`frontend/src/types.ts`, ~L4114) and `DEFAULT_SURVEY_APPEARANCE`
  (`posthog/constants.py`, ~L336). Per-survey write validation/sanitization lives in
  `SurveySerializerCreateUpdateOnly.validate_appearance` (`products/surveys/backend/api/survey.py`)
  and, on the client, in `sanitizeSurveyAppearance` / `validateSurveyAppearance`
  (`frontend/src/scenes/surveys/utils.ts`).
- **Built-in preset themes (client-only).** `surveyThemes: SurveyTheme[]` in
  `frontend/src/scenes/surveys/constants.tsx` (~L821) defines six presets (`clean`, `ocean`,
  `sunset`, `carbon`, `midnight`, `noir`) as `Partial<SurveyAppearance>`. They are rendered by
  `wizard/SurveyThemeSelector.tsx` and never persisted — selecting one merges its partial
  appearance into the survey.
- **Single project default appearance (persisted).** `Team.survey_config` is a JSON blob shaped
  `{"appearance": {...}}` (`posthog/models/team/team.py`, ~L443, access-controlled
  `project`/`admin`). Edited in **Project settings → Surveys → "Default survey appearance"**
  (`SurveySettings.tsx` → `SurveyDefaultAppearance`). New surveys seed their appearance from
  `{ ...defaultSurveyAppearance, ...currentTeam.survey_config?.appearance }`
  (`surveyLogic.tsx`, ~L1658).
- **Editor Customization panel.** `Customization` in
  `frontend/src/scenes/surveys/survey-appearance/SurveyCustomization.tsx`, wired into
  `SurveyEdit.tsx` (~L1311) under a `LemonField name="appearance"`. It already embeds the
  `SurveyThemeSelector` at the top of the panel.
- **Live preview.** `SurveyAppearancePreview.tsx` renders via posthog-js's real
  `renderSurveysPreview`, reused in the editor, the appearance modal, and settings.
- **Feature gate.** Styling is gated by `AvailableFeature.SURVEYS_STYLING`
  (`posthog/constants.py`, ~L34) surfaced as `surveysStylingAvailable` /
  `globalSurveyAppearanceConfigAvailable` in `surveysLogic.tsx`.

The gap this feature fills: there is no concept of **multiple, named, persisted, shared**
themes. Built-in presets aren't editable or extendable; the project default is a single
unnamed blob.

## Goals

- Save the current editor appearance as a named theme from inside the Customization panel.
- Themes are project-scoped and visible to every member of the project.
- Saved themes appear in the theme picker alongside built-in presets, in both the classic
  editor and the guided wizard.
- Applying a theme copies its appearance into the survey (a starting point, matching today's
  built-in-preset behavior) — it does not create a live link.
- Manage themes (rename, update from current appearance, delete) from a dedicated surface.

## Non-goals

- **No live/linked theming.** Editing a theme does not restyle surveys already using it. Surveys
  hold their own `appearance` copy. (Called out as a future consideration below.)
- **No org- or instance-level themes.** Scope is the team/project, matching `survey_config`.
- **Not replacing the project default appearance** in this iteration. The default stays as-is;
  see "Relationship to the default appearance" for the optional unification.
- **No theme marketplace / cross-project sharing / import-export.** Later, if wanted.

## What a "theme" captures

A theme stores the **visual** subset of `SurveyAppearance`, not survey content or
instance-specific fields. This matches the built-in presets, which are `Partial<SurveyAppearance>`
of mostly colors.

- **Include (visual):** `backgroundColor`, `textColor`, `textSubtleColor`, `borderColor`,
  `borderRadius`, `boxShadow`, `boxPadding`, `maxWidth`, `fontFamily`, `zIndex`,
  `disabledButtonOpacity`, `submitButtonColor`, `submitButtonTextColor`, `ratingButtonColor`,
  `ratingButtonActiveColor`, `inputBackground`, `inputTextColor`, `position`, `tabPosition`.
- **Exclude (content / per-survey):** `submitButtonText`, `backButtonText`, `placeholder`,
  `thankYouMessage*`, `shuffleQuestions`, `allowGoBack`, `surveyPopupDelaySeconds`,
  `autoDisappear`, and widget-instance fields `widgetType` / `widgetSelector` / `widgetLabel` /
  `widgetColor`.
- `whiteLabel` stays gated by `AvailableFeature.WHITE_LABELLING` exactly as it is per-survey; a
  theme may carry it, but applying/persisting still respects the org entitlement.

> **Decision point.** The include/exclude split above is a recommendation. If product wants
> themes to also standardize copy (e.g. a canonical thank-you message), widen the set — but keep
> widget-instance fields and popup delay out, since those are per-survey behavior. Define the
> canonical set in one place (`THEMEABLE_APPEARANCE_KEYS`) shared by validation and the "save"
> capture so it can't drift.

## Data model

Recommended: a dedicated, team-scoped model rather than growing `Team.survey_config` into an
array. It gives per-theme identity, activity logging, access-control hooks, and clean list/CRUD
without read-modify-write races on a shared JSON blob.

New model in `products/surveys/backend/models.py`:

```python
class SurveyTheme(TeamScopedRootMixin, UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="survey_themes")
    name = models.CharField(max_length=255)
    appearance = models.JSONField()  # visual subset of SurveyAppearance
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "name"], name="unique_survey_theme_name_per_team"),
        ]
```

- Use `TeamScopedRootMixin` so it is **fail-closed** from day one (see
  `posthog/models/scoping/README.md`) — reads without team context raise rather than leak across
  teams. Access one team's themes outside request context with
  `SurveyTheme.objects.for_team(team_id)`. This keeps the model off `baseline_unmigrated.txt`
  and passes the IDOR coverage check per the repo's tenant-isolation rule.
- Migration lives in `products/surveys/backend/migrations/` — follow `/django-migrations`
  (nullable/defaulted columns, no table rewrite; new table here so low risk).
- Unique `(team, name)` keeps the picker unambiguous; the API returns a friendly error on clash.

**Alternative considered — array inside `survey_config`.** Store
`survey_config.themes: [{id, name, appearance}]`. Lighter (no new table/migration) and rides the
existing `survey_config` plumbing, but every create/rename/delete is a read-modify-write of a
shared blob (lost-update risk with concurrent editors), there's no per-theme access control or
activity granularity, and it isn't independently queryable. Rejected as the primary design;
acceptable only if product wants the smallest possible surface first.

## API

New DRF viewset in `products/surveys/backend/api/`, registered in
`products/surveys/backend/routes.py` next to `SurveyViewSet`:

```python
routers.projects.register(r"survey_themes", SurveyThemeViewSet, "project_survey_themes", ["project_id"])
```

Endpoints (project-scoped, mirroring the surveys routes):

- `GET    /api/environments/:project_id/survey_themes/` — list workspace themes.
- `POST   /api/environments/:project_id/survey_themes/` — create `{ name, appearance }`.
- `PATCH  /api/environments/:project_id/survey_themes/:id/` — rename and/or update appearance.
- `DELETE /api/environments/:project_id/survey_themes/:id/` — delete.

Follow `/improving-drf-endpoints`:

- `SurveyThemeSerializer` (`ModelSerializer`) exposing `id`, `name`, `appearance`, `created_by`,
  `created_at`, `updated_at`, with `help_text` on every field so generated FE types and MCP
  schemas are populated.
- `validate_appearance` should **reuse the survey appearance sanitization** (the same
  `nh3`-based cleaning / white-label entitlement checks used by
  `SurveySerializerCreateUpdateOnly.validate_appearance`) and reject any key outside
  `THEMEABLE_APPEARANCE_KEYS`. Factor the shared sanitizer into a helper both serializers call so
  behavior can't diverge.
- Annotate methods with `@extend_schema` (or `@validated_request`) so drf-spectacular discovers
  the request body — required for non-empty generated schemas per repo architecture guidance.
- Regenerate types with `hogli build:openapi` (updates
  `products/surveys/frontend/generated/*` and `frontend/src/generated/core/*`).

**Access control.**

- **Read:** any project member (same as reading surveys).
- **Create / update / delete:** recommend gating writes so shared state isn't churned
  accidentally. Two reasonable options — pick one:
  1. **Project admins only** (consistent with `survey_config` being `project`/`admin`
     access-controlled). Simplest, matches the existing "shared appearance is an admin thing"
     precedent.
  2. **Any survey editor can create; creator + admins can edit/delete.** Lower friction for the
     "I just built a look, save it" flow that motivates this feature.
     > **Decision point.** Default to option 2 for the create path (the whole point is saving from
     > the editor without an admin round-trip) with admin-or-creator for destructive edits. Confirm
     > with product/security. Wire through the standard surveys access-control layer rather than
     > hand-rolled checks.
- Gate the whole feature behind `AvailableFeature.SURVEYS_STYLING`, matching existing styling
  gating. On the free tier the "Save as theme" affordance shows an upsell, and custom themes are
  hidden from the picker.

**Activity logging.** Log create / rename / update / delete under the existing `Survey`
activity scope (or a new `SurveyTheme` scope) so changes to shared workspace styling are
auditable, mirroring how `survey_config` edits already log a "global survey appearance" change.

## Frontend

Legacy note: the survey editor still lives at `frontend/src/scenes/surveys/` (only generated
code sits in `products/surveys/frontend/`). Build there and follow `frontend/src/AGENTS.md`
plus `/adopting-generated-api-types` (import the generated `SurveyTheme` API type; don't
hand-write it).

1. **New kea logic** `surveyThemesLogic.ts` (or extend `surveysLogic`): a `loaders`-backed
   `themes` list with `createTheme`, `updateTheme`, `deleteTheme` actions calling the generated
   API. Keep all logic in kea, not React hooks, per repo conventions. Loading/disabled states on
   every mutating control (double-submit guard is required by repo frontend rules).

2. **"Save as theme" affordance** in
   `survey-appearance/SurveyCustomization.tsx`, near the `SurveyThemeSelector` at the top of the
   panel. Opens a small modal (name input + live `SurveyAppearancePreview` of the current
   appearance). On submit it captures the `THEMEABLE_APPEARANCE_KEYS` subset of the survey's
   current `appearance` and POSTs a theme. Show name-collision errors inline. Disable + spinner
   while the request is in flight.

3. **Theme picker** (`wizard/SurveyThemeSelector.tsx`): render two groups — "Your workspace
   themes" (from the API) and "Built-in" (the existing `surveyThemes`). Selecting either merges
   its `appearance` into the survey via the existing `onAppearanceChange` path — identical to how
   presets work today, so no new apply semantics. `getMatchingSurveyThemeId` should also match
   against custom themes so the picker highlights the active one. Custom cards get overflow
   actions (rename, "update from current appearance", delete) subject to the write permission
   above.

4. **Manage themes surface.** Reuse **Project settings → Surveys** (`SurveySettings.tsx`,
   settings id `environment-surveys` in `SettingsMap.tsx`): add a "Workspace themes" section
   listing themes with edit/delete, next to the existing "Default survey appearance". Editing a
   theme opens the same `Customization` + preview UI already used for the default appearance.

5. **Types.** Add a `SurveyThemeType` (persisted) distinct from the existing client-only
   `SurveyTheme` preset interface, or unify them under one shape with a `source: 'builtin' |
'custom'` discriminator so the picker can treat both uniformly. Prefer the generated API type
   as the source of truth for the persisted shape.

## Behavior details & edge cases

- **Apply is a copy, not a link.** Applying a theme writes its values into the survey's
  `appearance`; later per-survey tweaks don't affect the theme, and later theme edits don't
  affect the survey. This matches built-in presets and keeps surveys self-contained.
- **Partial application.** A theme only sets its included keys; other appearance keys on the
  survey (copy, widget config, popup delay) are untouched on apply.
- **Deleting a theme in use** is safe — surveys keep their copied appearance. The picker simply
  stops offering it; `getMatchingSurveyThemeId` falls back to "no matching theme".
- **Rename** updates the shared record; anyone's picker reflects it on next load.
- **White-label** values in a theme still require `AvailableFeature.WHITE_LABELLING` when applied
  and persisted on a survey; don't let a theme smuggle white-labeling past the entitlement.
- **Name collisions** across concurrent creators are prevented by the unique `(team, name)`
  constraint; surface a clean validation error.
- **Empty state.** With no custom themes yet, the picker shows only built-ins plus a subtle
  "Save your first workspace theme" hint pointing at the current customization.

## Relationship to the default appearance (optional, future)

The single `Team.survey_config.appearance` default could later be reframed as "the default
theme" — a flag `is_default` on `SurveyTheme`, with new surveys seeding from the default theme
instead of the raw blob. Out of scope here to avoid a migration of existing `survey_config`
data, but the model leaves room for it (add a nullable/one-per-team default flag later).

## Testing

Per `/writing-tests` — each test must catch a realistic regression through the public interface.

- **Backend (pytest):** team-scoping is enforced (a theme from team A is invisible to team B);
  create/list/patch/delete happy paths; unique-name conflict returns a clean 400; appearance
  validation rejects non-themeable / unsafe keys and reuses the survey sanitizer; write
  permission enforced per the chosen access model; `SURVEYS_STYLING` gating; activity log entries
  written. Parameterize the appearance-validation cases.
- **Frontend (Jest):** `surveyThemesLogic` loader/mutation flows; `SurveyThemeSelector` renders
  both groups and applies a theme by merging appearance; "Save as theme" captures only the
  themeable subset and guards against double-submit; deleting an in-use theme leaves the survey's
  appearance intact.
- **Type generation:** run `hogli build:openapi` and check the generated survey-theme types in.

## Rollout

- Ship behind `AvailableFeature.SURVEYS_STYLING` (already the styling gate) — optionally add a
  short-lived feature flag to dark-launch the editor affordance.
- No data backfill required; `survey_config` default appearance is untouched.
- Docs: update the surveys product docs and any styling how-to in the same PR (repo rule: a doc
  change touching user-facing behavior ships with the code).

## Open questions

1. Write permission model — admin-only vs. any-editor-create + admin/creator-edit (recommended
   the latter for create; confirm).
2. Exact `THEMEABLE_APPEARANCE_KEYS` set — should copy fields (thank-you message) be themeable, or
   strictly visual?
3. Should applying a theme be undoable in-editor (it's just a form change today, so Ctrl-Z/leave-
   without-save already covers it — confirm that's enough)?
4. Do we want a per-team default theme now, or keep `survey_config.appearance` as the default and
   defer unification?
