---
name: suggesting-path-cleaning-rules
description: 'Runs and reasons about the automated AI health check that suggests path-cleaning rules for web-analytics teams. Use when asked to generate path-cleaning suggestions for a team or cohort, to run the suggestion check, to review/apply AI-suggested rules, to inspect path_cleaning_suggestions health issues, or to extend the suggestion pipeline. Covers the suggest_path_cleaning_rules management command, the path_cleaning_suggestions health check, the cohort gating (precompute teams), and how suggestions are validated against real paths before storage. For hand-authoring or applying rules directly, use managing-path-cleaning-rules instead.'
---

# Suggesting path-cleaning rules

Many teams never configure path cleaning, so their Web analytics breakdowns fragment across
thousands of near-identical URLs. This feature **proactively suggests** cleaning rules for the
web-analytics precompute cohort: weekly, for each team, it samples real paths, asks the LLM for
`{regex, alias}` rules, validates them against the team's own paths, and stores them for review.

It **only suggests** — it never auto-applies. Applying rewrites historical numbers in every cleaned
chart, so that stays a human decision (the existing settings UI, or the `--apply` flag below after
review). To hand-author or directly apply rules, use the `managing-path-cleaning-rules` skill.

## Architecture

- **Core**: `products/web_analytics/backend/path_cleaning_suggestions/service.py`
  - `sample_pathnames` / `count_distinct_pathnames` — top `$pathname` by views via HogQL.
  - `call_llm_for_rules` — one-shot call through the LLM gateway
    (`get_llm_client(product="web_analytics", team_id=...)`, model
    `WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS_MODEL`, default `claude-haiku-4-5`).
  - `validate_and_annotate_rules` — compiles each regex with **re2** (the engine ClickHouse
    `replaceRegexpAll` uses) and test-applies it to the sampled paths. Rules that don't compile or
    match nothing are dropped; survivors get a dense `order`, a `match_count`, and in-memory
    before/after `examples` (printed by the management command, never stored — health-issue
    payloads are readable with just `health_issue:read` and must not leak real paths). This is
    the skill's "test before saving" step, automated.
  - `generate_suggestions_for_team` — orchestrates the above with gating (see below); pure
    generation, no storage.
  - `apply_suggestions_to_team` — **merges** rules into `path_cleaning_filters`, never overwrites
    (dedupes by regex, continues `order`).
- **Storage**: a `path_cleaning_suggestions` **health issue** (`HealthIssue`, severity `info`) — no
  dedicated model. One active issue per team (`hash_keys=[]`); `payload` carries `rules`, `model`,
  `sampled_path_count`, `distinct_path_count`. Applying (or hand-configuring rules) resolves the
  issue on the next check run; dismissal is the health-issue `dismissed` flag.
- **Schedule**: `PathCleaningSuggestionsCheck`
  (`products/web_analytics/backend/temporal/health_checks/path_cleaning_suggestions.py`), a health
  check on the shared health-check framework, weekly (Mon 06:23 UTC), small sequential batches
  because each eligible team costs an LLM call. Teams with an existing active suggestion are
  re-emitted without a fresh LLM round trip.
- **Cohort**: `WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS_TEAM_IDS`, defaulting to the precompute
  enrollment list `WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS`.

## Gating (why a team is skipped)

`generate_suggestions_for_team` returns a status:

- `skipped_inactive` — team sent no `$pageview` within `visited_within_days` (default 30); we only
  suggest for teams actively using web analytics. Bypass with `--ignore-visit-gate`.
- `skipped_configured` — team already has path cleaning rules (override with `include_configured`).
- `skipped_low_cardinality` — fewer distinct paths than `min_distinct_paths` (default 50); cleaning
  adds no value, so we don't spend tokens.
- `skipped_no_paths` — no pageviews in the window.
- `generated` — rules produced (may be an empty list if paths are already clean; empty generations
  are never stored, so they can't shadow an actionable suggestion).
- `error` — sampling/LLM failed; captured per-team, never aborts the cohort sweep.

## How users see and apply suggestions

- **Settings banner**: `PathCleaningSuggestionsBanner` on `/settings/project#path_cleaning` shows the
  latest `suggested` row as regex → alias previews with match counts; "Apply all" (project admins
  only) merges the rules, the close button dismisses. Driven by `pathCleaningSuggestionsLogic`.
- **Onboarding step**: `OnboardingWebAnalyticsPathCleaningStep` (stepKey `path_cleaning`) surfaces the
  same banner during Web analytics onboarding.
- **API** (`products/web_analytics/backend/api/web_analytics_path_cleaning_suggestions.py`):
  `POST /api/projects/:id/web_analytics_path_cleaning_suggestions/generate/` produces and stores a
  fresh suggestion on demand; `GET .../{issue_id}/preview/` applies the rules to a fresh sample of
  the team's top paths and returns before/after pairs (read scope, computed on demand, never
  stored — this backs the banner's "Preview on your paths" modal); `POST .../{issue_id}/apply/`
  merges the rules and resolves the issue (project admin only — the same gate the team API puts on
  `path_cleaning_filters`).
  Listing and dismissing go through the generic health-issues API
  (`GET /api/projects/:id/health_issues/?kind=path_cleaning_suggestions&status=active&dismissed=false`,
  `PATCH .../health_issues/{id}/` with `{"dismissed": true}`).
- **Health page**: the check renders on `/web/health` alongside the other web-analytics checks, with
  remediation guidance for humans and agents.
- **PostHog AI (Max)**: generate/apply are exposed as MCP tools in
  `products/web_analytics/mcp/tools.yaml` (`web-analytics-path-cleaning-suggestions-{generate,apply}`),
  so a user can ask Max to suggest path-cleaning rules and apply them conversationally. Apply is
  `destructive` (it changes historical chart numbers), so the MCP confirmation gate applies.

## Running it

```sh
# Default cohort, print suggestions, store health issues:
python manage.py suggest_path_cleaning_rules

# Specific teams, dry run (nothing stored):
python manage.py suggest_path_cleaning_rules --teams 2,19279 --no-store

# Generate AND apply for one reviewed team (merges, never overwrites):
python manage.py suggest_path_cleaning_rules --teams 2 --apply
```

Useful flags: `--days` (lookback), `--limit` (top-N paths sampled), `--min-distinct-paths`,
`--include-configured`, `--no-store`, `--apply`.

The health check can also be triggered per team from the health-issues `refresh` endpoint or the
admin UI, like any other health check.

## Reviewing suggestions

Read a team's active suggestion:

```python
HealthIssue.objects.filter(team_id=team_id, kind="path_cleaning_suggestions", status="active").first()
```

Each rule in `payload["rules"]` carries `regex`, `alias`, `order`, `reason`, and `match_count` —
that's what to show a human deciding whether to apply. Before/after examples on real paths are only
printed by the management command at generation time; they are deliberately kept out of the stored
payload.

## Extending

- Adding a surfacing channel (in-app notification, settings banner, onboarding wizard step): read the
  team's active `path_cleaning_suggestions` health issue and render its `payload["rules"]`. Keep
  apply manual.
- Changing the model: it must be allowlisted for the `web_analytics` product in
  `services/llm-gateway/src/llm_gateway/products/config.py`.
- The agentic alternative — a `signals-scout-web-analytics-path-cleaning` scout — is sketched in the
  design notes; prefer the dedicated job for the precompute cohort because it targets that exact
  cohort and surfaces structured, validated rows rather than Signals-inbox findings.
