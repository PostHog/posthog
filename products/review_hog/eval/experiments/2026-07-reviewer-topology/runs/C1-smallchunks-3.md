# Reviewer-quality run — `C1-smallchunks-3`

- **Dumped:** 2026-07-01T21:51:15+00:00
- **Report id:** `019f1f9d-b2d4-7837-b43b-1a42bac50d9f` · **PR:** https://github.com/PostHog/posthog/pull/62096
- **Head:** `ba725a897db35053525e5bdfac2c64a8b007fcb4` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 813s (13.6 min)

## Config snapshot

- runtime / model / effort: `claude` / `claude-opus-4-8` / `xhigh`
- `EXPERIMENT_FORCE_CHUNKING` = True
- effective chunk target / soft-max additions = 250 / 400
- `EXPERIMENT_SEQUENTIAL_PERSPECTIVES` = False
- `EXPERIMENT_COMPLETENESS_PASS` = False

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 2      | 6            | 6          | 4           | 3                |

- **review units** = every (perspective|gap × chunk) sandbox review that ran = the model-held-constant cost proxy.
- **local `$ai_generation` tokens (best-effort, may be pre-ingestion / partial):**

  | model             | gens    | input tok    | output tok |
  | ----------------- | ------- | ------------ | ---------- |
  | claude-opus-4-8   | 103     | 10895329     | 101034     |
  | claude-sonnet-4-6 | 8       | 292378       | 4078       |
  | **total**         | **111** | **11187707** | **105112** |

## Chunking

- **chunk 1** (5 files): ee/hogai/tools/actions/core.py, ee/hogai/tools/actions/tool.py, ee/hogai/tools/actions/**init**.py, ee/hogai/tools/**init**.py, ee/hogai/chat_agent/toolkit.py
- **chunk 2** (4 files): frontend/src/queries/schema/schema-assistant-messages.ts, frontend/src/scenes/max/max-constants.tsx, frontend/src/queries/schema.json, posthog/schema_enums.py

## Per-review-unit breakdown

| pass | chunk | perspective                                    | raw issues |
| ---- | ----- | ---------------------------------------------- | ---------- |
| 1    | 1     | review-hog-perspective-contracts-security      | 2          |
| 1    | 2     | ?                                              | 0          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 1          |
| 3    | 1     | review-hog-perspective-performance-reliability | 1          |
| 3    | 2     | ?                                              | 0          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] consider · best_practice — frontend/src/scenes/max/max-constants.tsx:176-227

**Action tools never surface in the mode-selector capability list despite being available in all modes**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The five new action tools are added to TOOL_DEFINITIONS but are not included in DEFAULT_TOOL_KEYS (lines 151-161) and declare no `modes`. Both getDefaultTools() (which maps DEFAULT_TOOL_KEYS) and getToolsForMode() (which filters by `tool.modes?.includes(mode)`) are the only sources for the 'what Max can do' tooltip built in ModeSelector.tsx (buildModeTooltip at lines 134/151/222). Because these tools satisfy neither condition, they render in no mode's capability list. This contradicts the PR's stated intent that the tools are 'available across all agent modes' (wired into the backend DEFAULT_TOOLS) and is inconsistent with the comparable read/discovery tool `list_feature_flags`, which IS listed in DEFAULT_TOOL_KEYS. Note this is a discoverability/completeness gap only — the displayFormatters still resolve correctly via getToolDefinition(toolCall.name) when the LLM actually invokes a tool, so tool execution and status rendering are unaffected.
- **Suggestion:** If these tools are genuinely meant to be available in all modes (as the backend DEFAULT_TOOLS wiring implies), add the read/discovery ones (at minimum `list_actions` and `get_action`, mirroring how `list_feature_flags` is treated) to DEFAULT_TOOL_KEYS so they appear in the auto/plan-mode tooltip. Confirm the intended surfacing for the write tools (`create_action`, `update_action`, `delete_action`) and either add them to DEFAULT_TOOL_KEYS or give them an appropriate `modes` entry so users can discover them in the capability list.
- **Validator:** Investigation confirms the reviewer's factual premise but shows the issue is not worth surfacing. The five action tools do indeed lack both a `DEFAULT_TOOL_KEYS` entry and a `modes` property, so they won't appear in the 'what Max can do' capability tooltip built by `buildModeTooltip` in ModeSelector.tsx. However, this is the norm, not an anomaly: roughly 43 pre-existing TOOL*DEFINITIONS entries follow the exact same pattern — `call_mcp_server`, `todo_write`, `task`, `upsert_dashboard`, `create_notebook`, `search_session_recordings`, `filter_session_recordings`, all seven `marketing*\*`tools, and the task-tracker tools all have neither`modes` nor a DEFAULT_TOOL_KEYS entry and are likewise absent from every mode's capability list. The reviewer's 'inconsistent with list_feature_flags' argument cherry-picks the one comparable tool that IS listed while ignoring the many read/discovery tools that are not. Critically, the issue is self-admittedly cosmetic: 'a discoverability/completeness gap only — tool execution and status rendering are unaffected' because displayFormatters resolve via getToolDefinition(toolCall.name) at invocation time. There is no correctness, security, data-loss, contract, performance, or reliability defect — the tools work fully when the LLM invokes them. Whether to surface tools in the mode-selector tooltip is a product/UX decision, and matching the surrounding convention (most tools are not surfaced) is defensible. This is a minor polish/completeness observation, below the bar of a real problem that plausibly affects users.

### [✅ VALID] must_fix (validator→should_fix) · security — ee/hogai/tools/actions/core.py:142-150

**list_actions bypasses object-level access control (information disclosure vs REST list contract)**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `list_actions` builds its queryset with only `Action.objects.filter(team=team, deleted=False)` and never applies object-level access filtering. The REST `ActionViewSet` (scope_object="action") runs every list queryset through `_filter_queryset_by_access_level` → `UserAccessControl.filter_queryset_by_access_level` (posthog/api/routing.py:362 and :386), which excludes actions a user has been explicitly object-level-blocked from (per-object AccessControl set to "none"), and — for a user with resource-level "none" but specific object grants — restricts the list to just those objects (plus ones they created). The established Max-tool pattern does the same: `products/replay_vision/backend/max_tools.py:554` filters its list queryset via `self.user_access_control.filter_queryset_by_access_level(...)`. This chunk deliberately added object-level `check_object_access` to `get_action`/`update_action`/`delete_action`, but `list_actions` was left unfiltered. As a result, a user who is object-level-denied on a specific action can still see that action's name, description, and full step definition through `list_actions`, even though `get_action` would (correctly) deny them and the REST list would omit it. This is an object-level access-control bypass / data-exposure gap that diverges from the REST contract the PR intends to mirror. (Note: the resource-level `none` case is separately blocked by `get_required_resource_access()` on `ListActionsTool`, but the per-object block case is not.)
- **Suggestion:** Apply object-level filtering to the list queryset before counting and slicing, mirroring the REST list path and the replay_vision Max tool. Because `list_actions` currently only receives `team`, thread the acting user's access control through — e.g. pass the tool's `UserAccessControl` (or a filter callable) into `list_actions` and do `qs = user_access_control.filter_queryset_by_access_level(qs)` right after the `team`/`deleted`/`search` filters (before `qs.count()` and slicing), so `total` and the returned rows both reflect only accessible actions. Alternatively construct and filter the queryset in `ListActionsTool._arun_impl` (which has `self.user_access_control`) and pass it in.
- **Validator:** Confirmed against the codebase. The REST ActionViewSet (scope_object="action", AccessControlViewSetMixin) filters list querysets through_filter_queryset_by_access_level → UserAccessControl.filter_queryset_by_access_level (posthog/api/routing.py:362,386), which excludes per-object-blocked actions from list results. This PR deliberately added object-level check_object_access to get_action/update_action/delete_action (tool.py:86,124,145) but left list_actions (core.py:142-150) filtering only on team/deleted/search. The established Max-tool pattern (products/replay_vision/backend/max_tools.py:554) applies filter_queryset_by_access_level to its list. The concrete trigger is a user with a per-object AccessControl of "none" on a specific action: get_action correctly denies them, but list_actions still returns that action's name, description, and full step definition — an object-level access-control bypass diverging from the REST contract the PR intends to mirror. The resource-level "none" case is separately covered by get_required_resource_access(), so only the per-object block leaks, but that leak is real and reachable. Valid to keep.

### [✅ VALID] should_fix · bug — ee/hogai/tools/actions/core.py:148-150

**list_actions does not validate lower bounds of limit/offset (negative values crash, limit=0 ignored)**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `ListActionsToolArgs.limit`/`offset` are plain `Optional[int]` with no `ge` constraint, and `list_actions` only clamps the upper bound (`min(limit or DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT)`). Two boundary conditions are mishandled: (1) A negative `limit` or `offset` flows straight into `qs[start : start + capped_limit]`. Django 5.2 QuerySets reject negative slice indices with `ValueError: Negative indexing is not supported.`. Because `ListActionsTool._arun_impl` wraps `list_actions` in no try/except (unlike the other tools), this surfaces as an unhandled tool exception rather than a retryable/user-fixable error — e.g. the LLM computing `offset = start + len(actions)` on an empty page, or simply passing `limit=-1`, hard-crashes the tool. (2) `limit=0` is falsy, so `limit or DEFAULT_LIST_LIMIT` silently returns 25 instead of honoring the documented `1-{MAX_LIST_LIMIT}` range. The LLM has no way to learn a 0/negative value was invalid.
- **Suggestion:** Constrain the inputs at the schema (`limit: Optional[int] = Field(default=None, ge=1, le=MAX_LIST_LIMIT)`, `offset: Optional[int] = Field(default=None, ge=0)`) and/or clamp defensively in `list_actions` (e.g. `start = max(offset or 0, 0)` and `capped_limit = max(1, min(limit or DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT))`). This keeps a bad value on the retryable/validation path instead of raising an unhandled `ValueError` from the ORM slice.
- **Validator:** Confirmed against the code. `ListActionsToolArgs.limit`/`offset` are plain `Optional[int]` with no `ge` bound, so negative values pass pydantic validation and flow into `list_actions` (core.py:148-150). A negative `offset` makes `start` negative and `qs[start : start + capped_limit]` a negative slice; a negative `limit` makes `capped_limit` negative, again producing a negative slice stop. Django QuerySets reject negative indexing with `ValueError: Negative indexing is not supported.`. `ListActionsTool._arun_impl` (tool.py:69-73) calls `list_actions` with no try/except (unlike Create/Update/Delete which map `ActionToolError` to `MaxToolRetryableError`), so this surfaces as an unhandled tool exception the LLM can't recover from, rather than a clean retryable/validation error. The `limit=0` → 25 case is a smaller correctness/consistency gap (`limit or DEFAULT` treats 0 as unset, contradicting the documented `1-100` range). Inputs here are LLM-generated, so out-of-range values are plausible if uncommon, and the fix (pydantic `ge` constraints and/or defensive `max()` clamps) is trivial and puts bad values on the retryable path. This is a genuine reliability defect with a nameable trigger and consequence, not defensive paranoia — keep. should_fix is appropriate: real crash path but low likelihood and low blast radius (a single erroring tool call).

### [✅ VALID] should_fix · bug — ee/hogai/tools/actions/core.py:147-150

**Pagination ordering is non-deterministic (order_by("name") has no stable tiebreaker)**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `list_actions` pages results with `qs.order_by("name")` and then slices by `offset`/`limit`. `Action.name` is nullable (`null=True`) and has no DB-level unique constraint — uniqueness is only enforced at the application layer (`_check_name_available`) and only for non-deleted rows, so legacy/imported data and NULL names can produce duplicate or missing sort keys. Ordering by `name` alone leaves ties resolved arbitrarily by Postgres, and that resolution can differ between the successive queries used to walk pages. As a result, offset-based paging (which the tool actively encourages via `limit`/`offset` and the 'increase offset to N for the next page' footer) can silently skip some actions and return others twice across pages — the agent gets an incomplete or inconsistent view of the project's actions.
- **Suggestion:** Add a stable secondary sort key so the ordering is fully deterministic across page requests, e.g. `qs = qs.order_by("name", "id")`. This guarantees a total order regardless of duplicate/NULL names and makes offset paging correct.
- **Validator:** Verified. `list_actions` orders with `qs.order_by("name")` (core.py:147) then slices by `offset`/`limit`, and `Action.name` is nullable with no DB-level unique constraint — uniqueness is only enforced application-side (`_check_name_available`) among non-deleted rows, so NULL/empty names and legacy or case-variant duplicates are possible within a team. Offset pagination over a non-unique sort key is a textbook correctness bug: Postgres does not guarantee a stable resolution of ties across the successive LIMIT/OFFSET queries used to walk pages, so rows can be silently skipped or returned twice. The tool actively promotes multi-call paging (the `limit`/`offset` args and the 'increase offset to N for the next page' footer), so the defective path is one the design encourages, and the fix (`order_by("name", "id")` for a total order) is a trivial one-liner. The premise holds and the trigger (duplicate/NULL names + paging) is reachable, so keep. should_fix is reasonable: genuine correctness defect on the paging path, but observable harm requires the uncommon duplicate/NULL-name condition and yields an inconsistent agent view rather than data loss.
