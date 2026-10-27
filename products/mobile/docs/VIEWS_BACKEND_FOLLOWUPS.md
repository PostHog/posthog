# Views tab: backend follow-ups

The Views tab uses only the APIs that exist today, and it makes no backend change.
This file lists the backend work that would unlock more for Views users.
For each item, it also names the app change that follows when the backend work lands.

## Summary

Ranked by user value, highest first.

| Item                                                      | What users get                                                                | Backend change                                                                                                       | Size | Priority                                               |
| --------------------------------------------------------- | ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | ---- | ------------------------------------------------------ |
| 1. Refresh on focus, checked on the server                | Views refresh when they come back into focus, without a tap                   | The server enforces `next_allowed_client_refresh` for app callers: a forced read inside the window returns the cache | M    | P1                                                     |
| 2. Display mode and chosen tile sync across devices       | Number and Chart pins survive a new phone, a reinstall and a new sign-in      | Two nullable fields on `FileSystemShortcut`, with serializer fields and a migration                                  | S    | P1                                                     |
| 3. Insights viewed on the web appear in Recent            | Recent on the phone lists the insights the person opened on the web           | `required_scopes` on `insights/my_last_viewed/`                                                                      | XS   | P1                                                     |
| 4. Phone views count as "recently viewed"                 | Phone opens show in the web's "Recently viewed" and in Recent on other phones | The explicit `log_view` endpoint logs views for OAuth callers                                                        | S    | P2                                                     |
| 5. Pin order sync with the web's starred order            | One pin order on the phone and on the web                                     | `required_scopes` on `reorder` and `bulk_update`, project-wide scoping, and no `team_id` rewrite in `update()`       | S    | P2 (the `update()` fix is P1, because item 2 needs it) |
| 6. "New" badge for agent-built dashboards                 | A small badge on dashboards an AI agent built in the last 7 days              | Provenance fields on `Dashboard`                                                                                     | S    | P3                                                     |
| 7. Trustworthy freshness on capacity errors               | No API client shows "Updated just now" over a failed refresh                  | `last_refresh=None` on a rate-limited result with no data                                                            | XS   | P2                                                     |
| 8. A "Last year" date preset                              | One tap for the previous calendar year                                        | Fix `-1yEnd` in `posthog/utils.py`                                                                                   | XS   | P3                                                     |
| 9. SQL insight staleness matches its `cache_target_age`   | SQL insights refresh on the schedule their response describes                 | Align `_is_stale` and `cache_target_age` in `HogQLQueryRunner`                                                       | XS   | P3                                                     |
| Web, optional: a "Pinned" group in the new web navigation | Phone pins show in the web's Views pane                                       | Web only, no backend change                                                                                          | M    | Optional                                               |

Sizes: XS is under 100 changed lines, S under 300, M under 800, L over 800, tests included.
Priorities: P1 first, then P2, then P3.

## Items

Backend line numbers are from `origin/master` at `e9f815a9ced` (2026-10-14).
Check them again before you start.
App modules are the Views code in `src/features/views/`, `src/api/` and `src/model/views.ts`.

### 1. Refresh on focus, checked on the server

**What it enables:**
The app can force a refresh when a view comes back into focus, not only when the person taps refresh.
A check on the server makes that safe: a forced read inside the window returns the cache, whatever the client sends.

**Why it matters to users:**
People open a view on the phone to see the latest number.
Today, on focus, the phone shows the cached number until the server's staleness window passes.
For daily data that window is 6 hours.
People often refresh right after they open a view, so today they must pull to refresh each time.
With a server-side check, the app can do that refresh for them.

**What the app does today:**

- Open, focus and foreground never force. They send `refresh=blocking`, which computes only past `cache_target_age`.
- Pull and tile refresh read immediately, bypassing the device's automatic minute floor. They send `force_blocking` only for items whose `next_allowed_client_refresh` has passed, in server time with a 2 s margin, and honor the dashboard's shared rule based on `Dashboard.last_refresh`.
- Items inside their window, or without a known window, read cached results. The app adds no device-local five-minute floor.
- One queue (`src/features/views/refreshQueue.ts`) allows 2 requests in flight and one automatic request per item per 60 s. Manual reads still join existing requests, respect budgets and pause on `Retry-After`.
- Token buckets in `src/api/budget.ts` cap each budget family at 25% of the published limits.
- The window check lives in the app only, so forcing on focus would depend on every app version getting it right.

**Backend change:**

Enforce `next_allowed_client_refresh` on the server for app callers.

- Today the server sets the field on a fresh compute (`posthog/hogql_queries/query_runner.py:2800`), and the web honors it in its refresh controls.
  `force_*` computes inside the window (`:2481-2513`).
  Only shared links clamp a forced refresh (`shared_insights_execution_mode`, `:494-510`).
- The change: when the caller is not a browser session, run `force_blocking` as `RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE` and `force_async` as `RECENT_CACHE_CALCULATE_ASYNC_IF_STALE`.
  Set the staleness override to the runner's `_refresh_frequency()`.
  Inside the window the server then returns the cache. Past the window it computes, as a force does today.
- The runner already supports a per-request staleness override.
  `run(cache_age_seconds=...)` sets `_cache_age_override` (`query_runner.py:2327, 2344`), and `_is_stale_for_request` honors it (`:3362-3376`).
  The shared-link clamp uses the same mechanism (`:428-432, 494-510`).
- The window depends on the runner: the base `_refresh_frequency` is 1 minute (`:3385-3386`), and the insight runners use 3 or 15 minutes.
  So resolve the window inside the runner, for example with a flag on `run()` that sets the override from `_refresh_frequency()`.
- Apply the check in `resolve_execution_mode` (`posthog/hogql_queries/refresh_policy.py:71-93`) for insight and dashboard reads.
  Apply it in `_process_query_request` (`posthog/api/query.py:176-186`) for `POST query/`.
- Read the caller type from the `access_method` query tag.
  The OAuth authenticator sets it to `AccessMethod.OAUTH` (`posthog/auth.py:1058-1062`).
  `posthog/api/query.py:325, 332` read it with `get_query_tag_value("access_method")`.
- The platform owners decide which callers count as app callers.

Skills and tests:

- Invoke `/improving-drf-endpoints` and `/writing-tests`.
- Extend `posthog/hogql_queries/test/test_refresh_policy.py` with a parameterized table of refresh mode by access method.
  Add one runner test: a forced read inside the window returns the cached result.
- No migration and no OpenAPI change.

**App change when it lands:**

- `useViewRefresh` can send `force_blocking` on focus for each visible item that `isEligible` accepts ("force when the server allows").
- Keep `isEligible`, the queue and the token buckets. They keep the app inside the limits on older deploys and on self-hosted instances.

**Size:** M.

### 2. Display mode and chosen tile sync across devices

**What it enables:**
A pin's display mode (Row, Number or Chart) and the tile that a dashboard pin shows follow the person to every phone.

**Why it matters to users:**
People set up Number and Chart pins once.
Today a new phone, a reinstall or a new sign-in shows every pin as a Row again.
The person must then set up each pin again.

**What the app does today:**

- `src/features/views/pinPrefsStore.ts` keeps `display: Record<shortcutId, { mode, tileId?, insightId? }>` per project in AsyncStorage (store `views-pin-prefs:v2`).
  It clears on sign-out.
- No server field fits.
  `FileSystemShortcut` exposes only `path`, `type`, `ref`, `href` and `order` (`posthog/api/file_system/file_system_shortcut.py:29-38`), and a PATCH with other keys is a silent no-op.
  `User.ui_configuration` has a fixed schema, and each web save replaces it whole (`posthog/api/user.py:286-292`).

**Backend change:**

- Model: add two nullable fields to `FileSystemShortcut` (`posthog/models/file_system/file_system_shortcut.py:11-34`):
  - `display_mode`: a `CharField` with the choices `row`, `number` and `chart`. Null means Row.
  - `display_config`: a `JSONField`.
- Migration: two nullable `AddField` operations in `posthog/migrations/`, with no default, no backfill and no table rewrite.
  Invoke `/django-migrations`.
- Serializer: add both fields to `FileSystemShortcutSerializer.Meta.fields` (`posthog/api/file_system/file_system_shortcut.py:26-52`).
  Give each a `help_text` in `extra_kwargs`, like the other fields (`:44-52`).
  - Validate `display_config` with a typed nested serializer, not a free dict: `{tile_id: int, insight_id: int}`.
  - Allow it only for `type == "dashboard"` with a `number` or `chart` mode. Otherwise require null. Reject unknown keys.
  - Leave both fields out of `FileSystemShortcutBulkItemSerializer` (`:108-132`). The web's bulk path never sets them.
- Do the `update()` fix from item 5 first.
  Today a PATCH moves a sibling-environment pin into the route's environment (`:57-60`).
  A display-mode PATCH from the phone would then break the web's starred order for that pin.
- A rename rewrites only `path` and `href` (`posthog/models/file_system/file_system.py:84-94`), so the new fields survive renames.
- Run `hogli build:openapi` and commit the generated types.
  Invoke `/improving-drf-endpoints`.
- Tests: extend `posthog/api/file_system/test/test_file_system_shortcut.py` with one parameterized PATCH test.
  A valid mode and config round-trip. An invalid `display_config` returns 400.
  Invoke `/writing-tests`.

**App change when it lands:**

- `src/api/shortcuts.ts` reads `display_mode` and `display_config` from `GET file_system_shortcut/`.
  It writes them with `PATCH file_system_shortcut/{id}/`.
- `PinView.display` in `src/model/views.ts` comes from the server row.
- Detect support by the `display_mode` key in the list response.
  Older deploys and self-hosted instances keep the local store.
- Move local values up once: for each row with `display_mode: null` and a local entry, PATCH the row, then delete the local entry.
  After that the server is the only source. Two phones share one mode per pin, and the last write wins.

**Size:** S.

### 3. Insights viewed on the web appear in Recent

**What it enables:**
Recent on the phone lists the insights that the person opened on the web, next to the dashboards.

**Why it matters to users:**
People look at an insight on the web and later want to check it again on the phone.
Today they must search for it, because Recent shows only dashboards from the web.

**What the app does today:**

- Recent merges two sources:
  - views opened on this phone, kept on the device (last 20);
  - `GET dashboards/?ordering=-last_viewed_at&limit=10`, a per-user list that needs only `dashboard:read`.
- Insights viewed on the web do not appear.
  `GET insights/my_last_viewed/` is per user, but it returns 403 for OAuth.
  `GET insights/?order=-last_viewed_at` is team-wide (`products/product_analytics/backend/logic.py:68-72`), so it is not a substitute.
- The phone sends `POST insights/viewed/` on each insight open (`products/product_analytics/backend/presentation/insight.py:2381`).
  So the web's "Last viewed" already includes phone opens.

**Backend change:**

- `my_last_viewed` (`products/product_analytics/backend/presentation/insight.py:1987-1995`) is a custom action with no `required_scopes`.
  `_get_required_scopes` then returns `None`, and every token gets 403 "This action does not support personal API key access" (`posthog/permissions.py:698-725, 885-889`).
- Add `required_scopes=["insight:read"]` to its `@action`, as `viewed` does (`insight.py:2381`).
- Add `@extend_schema(responses=InsightBasicSerializer(many=True))`, so the generated types describe the response.
  Run `hogli build:openapi`.
  Invoke `/improving-drf-endpoints`.
- The action returns the last 5 insights that this user viewed, from `recently_viewed_insights` (`products/product_analytics/backend/logic.py:75-89`).
  The list includes phone opens, because `POST insights/viewed/` writes the same `InsightViewed` rows.
- Tests: `posthog/api/test/test_personal_api_keys.py:732-735` uses `my_last_viewed` as its example of an action without `required_scopes`.
  Point that test at another action that still has none.
  Add a case where a key with `insight:read` gets 200.
  Invoke `/writing-tests`.

**Alternative that needs only ops and an app change:**

- Request `file_system:read`, and read `GET file_system/?order_by=-last_viewed_at&not_type=folder&limit=20` (`posthog/api/file_system/file_system.py:275-281`; `_list_recents`, `:694-750`).
- This is the web's "Recently viewed" list. It is per user and per environment, and it covers dashboards, insights, notebooks and the other types that the web logs.
- It adds one more scope to the shared OAuth client (see "Ops and deploy checks"). Existing users must sign in again once.
- Phone opens are absent from this list until item 4 lands.

**App change when it lands:**

- `src/api/insights.ts` gets a `myLastViewed()` call.
- The Recent merge adds the insights as a third source.
  It dedupes by match key against the device list, drops pinned views and keeps the cap of 10.

**Size:** XS.

### 4. Phone views count as "recently viewed"

**What it enables:**
A dashboard or insight that the person opens on the phone counts as a view, the same as a web open.
The view then shows in the web's "Recently viewed", in the dashboards list ordered by `last_viewed_at`, and in Recent on the person's other phones.

**Why it matters to users:**
People move between the phone and the web.
Today a view opened on the phone is invisible everywhere else.
A reinstall also loses the phone's Recent list.

**What the app does today:**

- Recent keeps phone views in a device-local list (AsyncStorage, last 20). It clears on sign-out.
- The phone does not call `POST file_system/log_view/`. For OAuth it returns 204 and logs nothing.

**Backend change:**

- `log_view` (`posthog/api/file_system/file_system.py:1169-1196`) calls `log_api_file_system_view` (`posthog/api/file_system/file_system_logging.py:27-68`).
  That function returns early when the request has no session cookie (`:18-24, 40-41`).
- Let the explicit endpoint log a view for any authenticated, non-impersonated caller.
  For example, add a keyword `require_session_cookie: bool = True` to `log_api_file_system_view`, and pass `False` from `log_view`.
- Keep the cookie gate for implicit logging.
  `FileSystemViewSetMixin.retrieve` (`posthog/api/mixins.py:345-364`) and the recordings playlist API call the same function on reads.
  Without the gate, every API-key or OAuth read of a resource would fill "Recently viewed".
- Keep the impersonation checks: `@disallow_if_impersonated` (`file_system.py:1170`) and `is_impersonated_session` (`file_system_logging.py:43-44`).
  Check that an OAuth token minted during impersonation (`access_token.impersonated_by_id`, `posthog/auth.py:1055, 1071`) also counts as impersonated there.
- Scope: `log_view` is in `scope_object_write_actions` (`file_system.py:282-293`), so the POST needs `file_system:write`.
  That scope also allows create, move, link and delete in the file tree.
  Decide whether the POST should accept a narrower scope. `dangerously_get_required_scopes` can choose scopes per request (`posthog/permissions.py:704-709`).
- Effect: `GET dashboards/?ordering=-last_viewed_at` joins this user's `FileSystemViewLog` rows (`products/dashboards/backend/api/dashboard.py:2948-2958`).
  The `file_system/` recents read the same log. Both then include phone opens.
- Tests: extend the parameterized `test_log_view_endpoint_creates_entry` (`posthog/api/test/test_file_system.py:538`) with a bearer-token case.
  Add a case that a bearer-token GET of a dashboard still logs nothing.
  Invoke `/improving-drf-endpoints` and `/writing-tests`.
- No migration.

**App change when it lands:**

- On each dashboard and insight open, send `POST file_system/log_view/ {type, ref}` once.
  The dashboard `ref` is its id. The insight `ref` is its `short_id`.
  Send it once per open, not once per refresh.
- Add the scope to `OAUTH_SCOPES` in `src/auth/oauth.ts`, after the ceiling change (see "Ops and deploy checks").
- `file_system:write` covers `file_system:read`.
  So Recent can then read `GET file_system/?order_by=-last_viewed_at&not_type=folder` for every type.
  The device list becomes a fallback for older deploys.

**Size:** S.

### 5. Pin order sync with the web's starred order

**What it enables:**
The phone and the web share one pin order.
"Edit pins" and "Move up" / "Move down" on the phone change the web's starred order, and the reverse.

**Why it matters to users:**
People who arrange their stars on the web expect the same order on the phone.
Today each surface keeps its own order.
A new phone starts from the web's order again.

**What the app does today:**

- The phone never writes `order`.
  `src/features/views/pinPrefsStore.ts` keeps `rank: Record<shortcutId, number>` in AsyncStorage.
  New pins have no rank, so they go to the end, in server order.
- The phone cannot write the server order, for three reasons:
  - `POST file_system_shortcut/reorder/` and `bulk_update/` return 403 for OAuth.
    Both are custom actions without `required_scopes` (`posthog/api/file_system/file_system_shortcut.py:196, 231`).
  - Both actions filter the route environment (`team=self.team`, `:202-204` and `:239-241`), but the list is project-wide (`:167-189`).
    A pin from a sibling environment then fails with 400 "Unknown shortcut ids".
    The web shows "Could not save starred order" for the same reason (`frontend/src/layout/panel-layout/ProjectTree/projectTreeDataLogic.tsx:1088`).
  - A per-row `PATCH {order}` works for OAuth.
    But `update()` sets `team_id` to the route environment and `user` to the caller (`:57-60`).
    A PATCH from the phone moves a sibling-environment pin into the phone's environment.
    The web's reorder then fails for the person in the other environment.

**Backend change:**

- Add `required_scopes=["file_system_shortcut:write"]` to the `@action` of `reorder` (`:196`) and of `bulk_update` (`:231`).
- Scope both querysets like the list: this user's rows in every environment of the project (`_scope_by_project_and_environment`, `:170-174`), not `team=self.team`.
- `lock_user_shortcuts` keys its lock by team (`posthog/models/file_system/file_system_shortcut.py:40-48`).
  `create()` reads the last order per team (`file_system_shortcut.py:84-90`).
  If the writes become project-wide, key the lock and the last-order read by project too.
- Fix `update()` (`:57-60`): do not rewrite `team_id` or `user` on update.
  The queryset already limits rows to the caller's own (`:180`).
  Before you remove the two lines, read their history for the reason they exist.
- No migration.
  Run `hogli build:openapi` and commit any diff.
  Invoke `/improving-drf-endpoints`.
- Tests in `posthog/api/file_system/test/test_file_system_shortcut.py` (invoke `/writing-tests`):
  - `reorder` with a token that has `file_system_shortcut:write` returns 200.
  - `reorder` accepts ids from two environments of one project.
  - A PATCH from environment B keeps the `team_id` of a row made in environment A.
- This change also fixes the web's "Could not save starred order" error for stars from a sibling environment.

**App change when it lands:**

- "Edit pins" and "Move up" / "Move down" call `POST file_system_shortcut/reorder/ {ordered_ids}` through `src/api/shortcuts.ts`.
  On 400 "Unknown shortcut ids", refetch the list and retry once.
- The list renders in server order (`PinView.serverOrder` in `src/model/views.ts`).
- Upload the local order once, then drop `rank` from `pinPrefsStore.ts`.
- Detect support with the first `reorder` call.
  A 403 "This action does not support personal API key access" means an older deploy, so keep the local order.

**Size:** S.

### 6. "New" badge for agent-built dashboards

**What it enables:**
Recent marks a dashboard that an AI agent built in the last 7 days with a small "New" badge.

**Why it matters to users:**
People ask an agent, such as PostHog AI or a coding agent through MCP, to build a dashboard.
They check it later on the phone.
The badge helps them find what the agent made.

**What the app does today:**

- The app shows no badge.
- No dashboard field says which client created the dashboard.
  `Dashboard.creation_mode` (`products/dashboards/backend/models/dashboard.py:45-58, 80`) records default, template, duplicate or unlisted, not the client.
- A client rule such as "created in the last 7 days" cannot tell an agent from the person.

**Backend change:**

- Decide first where provenance lives: on `Dashboard` only, or on a model that every view type shares.
- Model: add two nullable fields to `Dashboard` (`products/dashboards/backend/models/dashboard.py:44`):
  - `created_via`: a `CharField` that holds an `EventSource` value (`posthog/event_usage.py:330-355`), for example `posthog_ai`, `mcp` or `wizard`;
  - `created_via_client`: a `CharField` that holds the sanitized MCP client name from `get_mcp_properties` (`posthog/event_usage.py:568`).
- Set both on create, from `get_event_source(request)` (`posthog/event_usage.py:487`):
  - in `DashboardSerializer.create` (`products/dashboards/backend/api/dashboard.py:1778`), next to the "dashboard created" event (`:1890-1900`);
  - in the create-from-template path (`:4012-4020`).
- Expose both fields read-only on `DashboardBasicSerializer` (`dashboard.py:1209`), each with a `help_text`.
  Run `hogli build:openapi`.
- Migration: two nullable `AddField` operations, with no default and no backfill.
  Old dashboards stay null and get no badge.
  Invoke `/django-migrations` and `/improving-drf-endpoints`, and run `hogli product:lint` for the `products/dashboards` isolation rules.
- Tests: one parameterized create test over event sources, in the dashboards API tests.
  Invoke `/writing-tests`.

**App change when it lands:**

- The dashboards adapter in `src/api/dashboards.ts` reads `created_via` and `created_at`.
- `RecentView` in `src/model/views.ts` gets a flag for "built by an agent in the last 7 days".
  The Recent row shows the badge.
  Write the badge copy with `/writing-user-facing-copy`.

**Size:** S, for dashboards only.

### 7. Trustworthy freshness on capacity errors

**What it enables:**
Every API client can trust `last_refresh` on an insight response.

**Why it matters to users:**
When the server is busy, an insight refresh fails and returns no result.
Today that response still says that the insight refreshed just now.
A client that trusts the field shows "Updated just now" over an old number, or over no number.

**What the app does today:**
The insight adapter takes `lastRefreshAt`, `cacheTargetAge`, `nextAllowedRefreshAt` and the value only from a response with a non-null result and no `query_status.error`.
Otherwise it keeps the previous snapshot and marks it `refreshFailed`.
The status line then says "Couldn't refresh" with the older age.

**Backend change:**

- The rate-limited branch of `InsightSerializer` (`products/product_analytics/backend/presentation/insight.py:1432-1459`) calls `_degraded_insight_result` (`:1461-1502`) with `last_refresh=now() if is_rate_limited else None` (`:1458`).
  The result in that response is `None`.
- Pass `last_refresh=None` instead, as the other degraded branch does (`:1430`).
- The web does not read the stamp.
  It treats a result-less error as a rejection and keeps the tile (`frontend/src/scenes/dashboard/dashboardUtils.ts:214-219`).
  Its retry keys on `error_code` and `error_message` (`:386-389`).
  The code does not say why the branch stamps `now()`, so read the history of that line first.
- Tests: add a `last_refresh is None` assertion to the parameterized `test_retrieve_labels_every_capacity_failure_as_rate_limited` (`products/product_analytics/backend/tests/api/test_insight.py:4268`).
  Invoke `/improving-drf-endpoints` and `/writing-tests`.
- No migration and no schema change.

**App change when it lands:**
None is needed.
Keep the adapter rule for older deploys and self-hosted instances.

**Size:** XS.

### 8. A "Last year" date preset

**What it enables:**
A one-tap "Last year" range, from January 1 to December 31 of the previous year, in the date range sheet.

**Why it matters to users:**
People who review a whole year need the previous calendar year.
Today they must step back from "This year", or pick both dates in the calendar.

**What the app does today:**
The date range sheet does not offer "Last year". The web has no such preset either.
The phone reaches last year with a step back from "This year", or with the custom calendar.
Both send absolute dates.

**Backend change:**

- `get_delta_mapping_for` (`posthog/utils.py:300-371`) handles the kind `y`.
  For the position `End` it sets only `day = 31` (`:368-369`).
  So `-1yEnd` resolves to the end of the current month one year ago, not to December 31.
  On 2020-01-31 it resolves to 2019-01-31.
- Set `month = 12` as well, the same way `Start` sets `month = 1` and `day = 1` (`:365-367`).
- Tests: `test_year` in `posthog/test/test_utils.py:434` runs at a frozen 2020-01-31.
  Add `-1yEnd` → `2019-12-31` and `yEnd` → `2020-12-31`, as a parameterized table like `test_quarter`.
  Invoke `/writing-tests`.
- Saved insights and dashboards that already use `-1yEnd` will show a different range after the fix.
  Search for them first. If any exist, invoke `/announcing-behavior-changes`.

**App change when it lands:**
Add "Last year" (`date_from: "-1yStart"`, `date_to: "-1yEnd"`) to the "More" presets in the date range sheet.
Add it only after US and EU run the fix.
Write the label with `/writing-user-facing-copy`.

**Size:** XS.

### 9. SQL insight staleness matches its `cache_target_age`

**What it enables:**
The `cache_target_age` of a SQL insight matches the time when the server actually recomputes it.

**Why it matters to users:**
Clients plan automatic refresh from `cache_target_age`.
Today a SQL insight says that it stays fresh for 6 hours, but a `blocking` or `async` read recomputes it after 5 minutes.
People see numbers change, and the server does work, on a schedule that the response does not describe.
This finding comes from a code reading. Nobody has run it yet.

**What the app does today:**
`dueAt` rechecks a visible item at most every 5 minutes, whatever its `cache_target_age` says.
For a SQL tile the server then recomputes, because its real staleness is 5 minutes.

**Backend change:**

- `HogQLQueryRunner.cache_target_age` (`posthog/hogql_queries/hogql_query_runner.py:66-70`) reports `last_refresh` plus the day threshold, 6 hours.
  Its comment says "Treat SQL query caching like day insight".
- The stale check is the base `_is_stale` (`posthog/hogql_queries/query_runner.py:3378-3383`).
  A HogQL runner has no `query_date_range`, so the check falls back to the `minute` interval, 5 minutes (`posthog/caching/utils.py:46-66`).
- `DataVisualizationNode` and `DataTableNode` insights use their source runner (`query_runner.py:633-641`), so SQL tiles on dashboards have the same mismatch.
- Pick one direction with the owners:
  - Make the check follow the comment. Override `_is_stale` in `HogQLQueryRunner`, and pass `target_age=self.cache_target_age(last_refresh, lazy)` to `is_stale` (`posthog/caching/utils.py:69-97` accepts it).
    SQL insights then recompute less often. Web users see that change, so consider `/announcing-behavior-changes`.
  - Or make `cache_target_age` report the 5 minutes that the check uses.
- Tests: first write a test in `posthog/hogql_queries/test/test_hogql_query_runner.py` that shows the mismatch, then fix it.
  Invoke `/writing-tests`.

**App change when it lands:**
None is needed, because `dueAt` already reads `cache_target_age`.
With the first direction, focus reads of SQL tiles become cache hits until 6 hours pass.

**Size:** XS.

## Web (not backend)

### Optional: a "Pinned" group in the new web navigation

This item is optional.
Mobile is a companion, not a copy of the web, and the app does not need this item.

**What it enables:**
Under the `today-rail-nav` flag, the web's Views pane shows the person's pins next to "Recently viewed" and "Views".
The pins are the same `FileSystemShortcut` rows that the phone uses.

**Why it matters to users:**
A person who pins a view on the phone finds it in the new web navigation without the ⌘K palette.

**What the app does today:**
Nothing. Phone pins are the web's stars.
They already show on the web in both navigations: in the ⌘K "Starred" group, and as the star state in dashboard and insight menus.

**Web change:**

- `frontend/src/layout/today/TodayViewsSidebar.tsx` renders "Recently viewed" (`:94`) and "Views" (`:109`) only.
  Add a "Pinned" group that reads `file_system_shortcut/` and offers pin and unpin on the same rows.
- Build it with quill, per `frontend/src/design.md`.
  Invoke `/writing-ui-components` and `/adopting-generated-api-types`.
- On 400 "Unknown shortcut ids" from `reorder`, refetch and retry once.
  Today `projectTreeDataLogic.tsx:1088` shows the toast "Could not save starred order" and stops.
- Add usage tracking, as the repo rules require for a new feature.

**App change when it lands:**
None. The empty Pinned copy can then mention the web.

**Size:** M.

## Ops and deploy checks (no code)

### OAuth scope ceiling, US and EU

- The Views tab needs `dashboard:read`, `insight:read` and `file_system_shortcut:write`, which covers `:read`.
  The app already has `query:read`.
  All three are unprivileged scopes that an OAuth app can request (`posthog/scopes.py:288-313`).
- Each OAuth application has a scope ceiling: `OAuthApplication.scopes` plus `optional_scopes`, two Postgres array columns (`posthog/models/oauth.py:144-172`).
  These are data rows, not code.
- `/authorize` drops a scope outside the ceiling without an error (`posthog/api/oauth/views.py:765-806`).
  The token works, the feature gets 403, and the server records an `oauth_scopes_clamped` event (`views.py:1520-1557`).

**Coordinate first.**
The app's two client ids (`products/mobile/src/auth/regions.ts:15-16`) are shared with two desktop-team mobile apps:

- `products/desktop/apps/mobile` (`src/features/auth/lib/constants.ts:3-4`);
- `products/desktop/apps/mobilehog` (`src/lib/oauth.ts:10-11`).

The ids are also in `POSTHOG_DESKTOP_OAUTH_CLIENT_IDS` (`posthog/temporal/oauth.py:33-34, 49-57`).
A ceiling change applies to all three apps.
Agree the change with the desktop team before anyone edits a row.

**To check**, in US and in EU:

1. Open Django admin at `/admin/posthog/oauthapplication/`. Find the row by client id.
2. Read `is_first_party` (`posthog/models/oauth.py:129`), `scopes` and `optional_scopes`. Write the values down.
3. If `scopes` and `optional_scopes` are both empty, or contain `@default`, change nothing.
   Every unprivileged scope is then grantable (`posthog/scopes.py:401-428, 561-562`).

**To edit**, when the ceiling is an explicit list:

- First-party row: add the scopes to `scopes`.
  Consent is skipped, and each app gets only the scopes it requests (`views.py:1658-1674`).
  - `python manage.py seed_oauth_app_scopes --client-id <id> --scopes "<full list>"` replaces the whole list.
  - The command refuses when the row has optional scopes, unless you pass `--clear-optional-scopes` (`posthog/management/commands/seed_oauth_app_scopes.py:28-117`).
    If the row has optional scopes, use Django admin.
- Other rows: every entry in `scopes` is required, and the consent screen grants all of them to every client of the row (`views.py:1678-1684, 1796-1829`).
  Add the scopes to `optional_scopes` in Django admin instead.
- `file_system_shortcut:write` alone is enough. An explicit ceiling also allows the read half of each listed `:write` scope (`posthog/scopes.py:559`).
- Write down the values after the change, per region.

**Order:**

- Change the ceiling before the app release that requests the scopes.
  Some paths answer `invalid_scope` instead of dropping the scope, and that blocks sign-in ([AUTH.md](AUTH.md), "Server-side ceiling").
- A token refresh never widens a grant (`posthog/api/oauth/views.py:808-851`).
  Existing users get the new scopes after one new sign-in.
- Items 3 (the alternative) and 4 add `file_system:read` or `file_system:write`.
  Repeat this check for them.

### Is #114532 deployed?

- #114532 (`8f3821e77c5`, "feat(insights): add a dashboard-level compare filter") lets a dashboard `filters_override` carry `compareFilter`.
  It is on master. We did not check its deploy to US and EU on 2026-10-14.
- To check, use one of these:
  - Find the commit that each region runs. Then run `git merge-base --is-ancestor 8f3821e77c5 <deployed-commit>`. Exit code 0 means that the region has it.
  - On a project you own, send `GET insights/{id}/?refresh=blocking&from_dashboard={d}&filters_override={"compareFilter":{"compare":true}}` for a trends tile.
    With the change, the result series carry `compare_label` `current` and `previous` (`products/product_analytics/backend/hogql_queries/trends/trends_query_runner.py:664`).
    Without it, `DashboardFilter` rejects the unknown key (`extra="forbid"`). The exact error is unverified.
- When both regions have it, set `DASHBOARD_COMPARE_SUPPORTED = true` in the app, and remove the note of the disabled toggle.
  Dashboards then send `compareFilter: {compare: true}` in the override of the dashboard read and of each tile read.
- World map, calendar heatmap and proportion bar tiles ignore compare (`_accepts_dashboard_compare_filter`, `trends_query_runner.py:1320-1329`).
  Show them without a compare row.
- Self-hosted instances on an older build do not accept the key.
