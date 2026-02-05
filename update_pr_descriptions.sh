#!/usr/bin/env bash
# Script to update PR descriptions for open claude/ PRs in PostHog/posthog
# Run: chmod +x update_pr_descriptions.sh && ./update_pr_descriptions.sh
# Requires: gh CLI authenticated with repo write access

set -euo pipefail

update_pr() {
  local pr_number="$1"
  local body="$2"
  echo "Updating PR #${pr_number}..."
  gh pr edit "$pr_number" --repo PostHog/posthog --body "$body"
  echo "  Done."
}

# PR #46896 - fix: display name nudge banner loading state logic
update_pr 46896 "$(cat <<'BODY'
## Summary

- Fix PersonDisplayNameNudgeBanner showing incorrectly during data refresh by removing `dataLoading` from the `shouldShow` calculation and adding an explicit loading guard to the render path
- Previously the banner would flash the "configure display properties" message while data was loading or when no results were returned

## Test plan

- [ ] Verify the banner does not appear while data is loading/refreshing
- [ ] Verify the banner still appears when display name properties genuinely need configuration
- [ ] Verify the banner hides correctly when a query returns no results
BODY
)"

# PR #46878 - feat(sql-editor): add user preference for new tab behavior
update_pr 46878 "$(cat <<'BODY'
## Summary

- Add a user preference for SQL editor new-tab behavior: users can choose between opening another SQL editor tab or opening the search bar
- Preference is stored in localStorage and accessible via Settings > User > Customization

## Test plan

- [ ] Verify the preference toggle appears under Settings > User > Customization
- [ ] Verify selecting "SQL editor" opens a new SQL editor tab on Cmd+T / new tab action
- [ ] Verify selecting "Search bar" retains the previous default behavior
- [ ] Verify the preference persists across page reloads
BODY
)"

# PR #46787 - fix(surveys): deduplicate responses by submission ID in summary endpoint
update_pr 46787 "$(cat <<'BODY'
## Summary

- Fix duplicate responses being sent to the LLM in the survey `summarize_responses` endpoint by adding `uniqueSurveySubmissionsFilter()` to the fetch query
- Multi-page surveys generate a separate "survey sent" event per page, causing the same submission to appear multiple times in summaries

## Test plan

- [ ] Verify multi-page survey summaries no longer contain duplicate responses
- [ ] Verify single-page survey summaries are unaffected
- [ ] Monitor `uniqueSurveySubmissionsFilter` for any regressions (it has caused issues previously)
BODY
)"

# PR #46780 - feat(product-tours): implement archive -> delete workflow like surveys (Draft)
update_pr 46780 "$(cat <<'BODY'
## Summary

- Implement a two-step archive-then-delete workflow for product tours, matching the existing survey deletion pattern
- Launched tours must first be archived (PATCH sets `archived: true`) before they can be permanently deleted (hard delete)
- Archive button now shows for all launched tours, with a warning for currently running tours
- Delete button restricted to draft and archived tours only

## Test plan

- [ ] Verify launched tours show an archive button (not delete)
- [ ] Verify archiving a running tour shows a warning dialog
- [ ] Verify archived tours show a delete button
- [ ] Verify draft tours show a delete button directly
- [ ] Verify deleting an archived tour permanently removes it
BODY
)"

# PR #46652 - feat(data-warehouse): add email notifications for materialized view sync failures
update_pr 46652 "$(cat <<'BODY'
## Summary

- Add email notifications when materialized view syncs fail, addressing #46021
- Introduces a `materialized_view_sync_failed` user preference to control notifications
- Uses campaign-based deduplication (current hour + saved query ID) to prevent duplicate emails
- Notification includes a direct link to the SQL editor for the failed saved query

## Test plan

- [ ] Verify email is sent when a materialized view sync transitions to FAILED
- [ ] Verify duplicate emails are not sent within the same hour for the same query
- [ ] Verify users can disable notifications via the `materialized_view_sync_failed` preference
- [ ] Verify the email contains a working link to the SQL editor
BODY
)"

# PR #46581 - chore: build hogvm package before starting dev server
update_pr 46581 "$(cat <<'BODY'
## Summary

- Fix Node.js service failing to start because `@posthog/hogvm` package was not built
- Update `prestart:dev` and `prestart:devNoWatch` scripts in `nodejs/package.json` to build hogvm via Turbo alongside the existing `build:cyclotron` command

## Test plan

- [ ] Verify `pnpm start:dev` successfully starts the Node.js service without manual hogvm build
- [ ] Verify the hogvm `dist/` folder is created during prestart
BODY
)"

# PR #46575 - chore: settings page
update_pr 46575 "$(cat <<'BODY'
## Summary

- Add a level toggle to the settings sidebar (Environment / Project / Organization / Account) behind the `BETTER_SETTINGS_PAGE` feature flag
- Allows users to quickly filter settings by hierarchy level instead of scrolling through all settings

## Test plan

- [ ] Verify the level toggle appears when `BETTER_SETTINGS_PAGE` flag is enabled
- [ ] Verify selecting a level filters the sidebar to only show settings for that level
- [ ] Verify search still works within the filtered view
- [ ] Verify the toggle does not appear when the feature flag is disabled
BODY
)"

# PR #46550 - chore: add lc_modifiers column to query_log_archive
update_pr 46550 "$(cat <<'BODY'
## Summary

- Add `lc_modifiers` String column to query log archive tables to store HogQL query modifiers (e.g. personsOnEventsMode, useMaterializedViews)
- Migration adds the column to sharded data tables, recreates writable distributed tables, and updates materialized views to extract modifier fields from the log_comment field

## Test plan

- [ ] Verify migration runs successfully on a fresh database
- [ ] Verify `lc_modifiers` column is populated for new queries with modifiers
- [ ] Verify existing query log entries are not affected
BODY
)"

# PR #46541 - fix: add vertical padding to search results loading skeleton
update_pr 46541 "$(cat <<'BODY'
## Summary

- Add vertical padding between loading skeleton rows in search results so rounded corners render cleanly
- Introduce an `inset` prop on `WrappingLoadingSkeleton` to support optional vertical spacing without causing layout shifts when actual results load

## Test plan

- [ ] Verify skeleton rows have visible spacing between them during loading
- [ ] Verify no layout shift occurs when results replace the skeleton
- [ ] Verify the skeleton without `inset` renders unchanged
BODY
)"

# PR #46496 - fix: memory leaks in session recording player reinitialization
update_pr 46496 "$(cat <<'BODY'
## Summary

- Fix memory leaks in session recording player by improving the cleanup sequence during reinitialization
- Guard against redundant reinitialization when a player already exists for the current window
- Dispose the old replayer before clearing DOM elements so it releases DOM references before they are removed

## Test plan

- [ ] Verify replayer is not recreated unnecessarily when the same window is selected
- [ ] Verify switching between recordings does not accumulate detached DOM elements (check via DevTools memory profiler)
- [ ] Verify playback still works correctly after switching between multiple recordings
BODY
)"

# PR #46400 - chore: remove REPLAY_X_LLM_ANALYTICS_CONVERSATION_VIEW feature flag
update_pr 46400 "$(cat <<'BODY'
## Summary

- Remove the `REPLAY_X_LLM_ANALYTICS_CONVERSATION_VIEW` feature flag and associated conversation preview functionality
- The AIEventSummary component and special handling for AI event types ($ai_generation, $ai_span, $ai_trace) are removed entirely as the feature did not work out
- AI events now render as regular events in the session recording inspector

## Test plan

- [ ] Verify AI events ($ai_generation, $ai_span, $ai_trace) display as regular events in session recording inspector
- [ ] Verify no references to the removed feature flag remain in the codebase
- [ ] Verify bundle size decreased
BODY
)"

# PR #45986 - Add Bearer token authentication for internal API routes (Draft)
update_pr 45986 "$(cat <<'BODY'
## Summary

- Add Bearer token authentication middleware for plugin server internal API routes (`/api/*`)
- Authentication is optional: disabled when `PLUGIN_SERVER_API_TOKEN` is empty, enabled when set
- Python API client (`plugin_server_api.py`) updated to include Bearer token headers when configured
- Returns 401 for invalid/missing tokens and logs unauthorized attempts

## Test plan

- [ ] Verify API routes return 401 when token is set but request has no/wrong Bearer token
- [ ] Verify API routes work normally when `PLUGIN_SERVER_API_TOKEN` is empty (backward compatible)
- [ ] Verify `/_health` endpoint remains accessible without authentication
- [ ] Verify Python API client sends correct Authorization header
- [ ] Address review feedback: use `crypto.timingSafeEqual()` for token comparison
BODY
)"

# PR #45964 - feat(data-warehouse): convert ExternalDataJob activities to async
update_pr 45964 "$(cat <<'BODY'
## Summary

- Convert eight Temporal workflow activities in the data warehouse module from synchronous to asynchronous
- Django ORM calls wrapped with `database_sync_to_async`, S3/Redis operations wrapped with `asyncio.to_thread()`
- Synchronous `HeartbeaterSync` replaced with async `Heartbeater` context manager

## Test plan

- [ ] Verify all converted activities execute successfully in the Temporal workflow
- [ ] Verify Django ORM calls are properly wrapped and don't trigger async safety warnings
- [ ] Verify S3 and Redis operations do not block the event loop
- [ ] Verify heartbeating works correctly with the async Heartbeater
BODY
)"

# PR #45956 - chore(data-warehouse): Upgrade deltalake to 1.4.0 and update deprecated API calls
update_pr 45956 "$(cat <<'BODY'
## Summary

- Upgrade deltalake from 0.25.2 to 1.4.0 and update deprecated API calls
- Replace `to_pyarrow()` with `to_arrow()`, `from_pyarrow()` with `from_arrow()`, and remove deprecated `engine="rust"` parameter
- Wrap `to_arrow()` results with `pa.schema()` for compatibility since deltalake 1.4.0 returns arro3-compatible objects

## Test plan

- [ ] Verify materialized view sync still works end-to-end
- [ ] Verify data import pipelines function correctly with the new API
- [ ] Verify pipeline utility tests pass
BODY
)"

# PR #45468 - feat(onboarding): AI-powered conversational onboarding with product discovery
update_pr 45468 "$(cat <<'BODY'
## Summary

- Introduce AI-powered conversational onboarding behind the `ONBOARDING_AI_PRODUCT_RECOMMENDATIONS` flag (`chat` variant)
- New `OnboardingChat` component with conversational UI, clickable product cards, typing indicators, and auto-scrolling
- Backend `AgentMode.ONBOARDING` with custom prompts and a `recommend_products` tool for AI-assisted product discovery
- Per-user rate limiting (20 free messages/day via Redis) with server-side concurrent request protection

## Test plan

- [ ] Verify the chat onboarding appears for users in the `chat` variant of the feature flag
- [ ] Verify product recommendations are displayed as clickable cards
- [ ] Verify the 20-message daily limit is enforced and shows a friendly message
- [ ] Verify the feature does not appear for users in the control group
- [ ] Verify non-billable mode prevents cost exploitation
BODY
)"

# PR #45440 - fix: disable date filter on data table when it would have no effect (Draft)
update_pr 45440 "$(cat <<'BODY'
## Summary

- Disable the date filter control on data tables when the underlying HogQL query does not include the `{filters}` placeholder
- Show an explanatory tooltip guiding users to add `{filters}` to their query to enable date filtering
- Prevents confusion from adjusting a filter that has no effect on results

## Test plan

- [ ] Verify the date filter is disabled when a HogQL query lacks `{filters}`
- [ ] Verify the tooltip explains how to enable date filtering
- [ ] Verify the date filter works normally when `{filters}` is present in the query
BODY
)"

# PR #44902 - feat(endpoints): add support for materializing endpoints with variables
update_pr 44902 "$(cat <<'BODY'
## Summary

- Add support for materializing endpoints whose queries contain variables (e.g. `WHERE event = {variables.event_name}`)
- Variables in WHERE clauses are transformed into GROUP BY dimensions in the materialized table, then reapplied as filters at query time
- New `analyze_variables_for_materialization()` and `transform_query_for_materialization()` AST utilities
- `Endpoint.can_materialize()` updated to permit single equality-operator variables

## Test plan

- [ ] Verify endpoints with a single variable in a WHERE clause can be materialized
- [ ] Verify the materialized table groups by the variable dimension correctly
- [ ] Verify querying the endpoint with a variable value returns correct filtered results
- [ ] Verify endpoints with unsupported variable patterns (multiple variables, non-equality operators) are rejected
BODY
)"

# PR #44824 - feat: lock clickmap to a container (Draft)
update_pr 44824 "$(cat <<'BODY'
## Summary

- Add ability to filter clickmap results to a specific container element via CSS selector
- New `container_selector` parameter on `/api/element/stats/` supporting class, ID, tag, Tailwind utility, and data attribute selectors
- Smart container detection walks up the DOM tree to find a suitable parent element, prioritizing data attributes, meaningful IDs, and semantic tags
- Filtering applied at both the backend API level and frontend DOM containment check

## Test plan

- [ ] Verify selecting a container in the toolbar filters clickmap to only show clicks within that container
- [ ] Verify the smart container detection picks a reasonable parent (not the click target itself)
- [ ] Verify CSS selector types work: `.class`, `#id`, `tag`, `[data-attr]`
- [ ] Verify clearing the container selector shows all clicks again
BODY
)"

echo ""
echo "All PR descriptions updated successfully!"
