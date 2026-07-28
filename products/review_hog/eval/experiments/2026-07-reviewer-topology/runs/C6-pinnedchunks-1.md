# Reviewer-quality run — `C6-pinnedchunks-1`

- **Dumped:** 2026-07-02T03:29:14+00:00
- **Report id:** `019f20d2-b4d5-7d4b-8c08-8cec90dbff69` · **PR:** https://github.com/PostHog/posthog/pull/62096
- **Head:** `ba725a897db35053525e5bdfac2c64a8b007fcb4` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 839s (14.0 min)

## Config snapshot

- runtime / model / effort: `claude` / `claude-opus-4-8` / `xhigh`
- `EXPERIMENT_FORCE_CHUNKING` = False
- effective chunk target / soft-max additions = 1000 / 1500
- `EXPERIMENT_SEQUENTIAL_PERSPECTIVES` = False
- `EXPERIMENT_COMPLETENESS_PASS` = False
- `EXPERIMENT_WARM_REVIEW_SESSION` = False
- `EXPERIMENT_PINNED_CHUNKS` = {1: ['ee/hogai/tools/actions/core.py'], 2: ['ee/hogai/tools/actions/tool.py', 'ee/hogai/tools/actions/**init**.py', 'ee/hogai/tools/**init**.py', 'ee/hogai/chat_agent/toolkit.py'], 3: ['frontend/src/scenes/max/max-constants.tsx', 'frontend/src/queries/schema/schema-assistant-messages.ts', 'frontend/src/queries/schema.json', 'posthog/schema_enums.py']}

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 3      | 9            | 9          | 5           | 3                |

- **review units** = every (perspective|gap × chunk) sandbox review that ran = the model-held-constant cost proxy.
- **local `$ai_generation` tokens (best-effort, may be pre-ingestion / partial):**

  | model           | gens    | input tok    | output tok |
  | --------------- | ------- | ------------ | ---------- |
  | claude-opus-4-8 | 192     | 18679218     | 160516     |
  | **total**       | **192** | **18679218** | **160516** |

## Chunking

- **chunk 1** (1 files): ee/hogai/tools/actions/core.py
- **chunk 2** (4 files): ee/hogai/tools/actions/tool.py, ee/hogai/tools/actions/**init**.py, ee/hogai/tools/**init**.py, ee/hogai/chat_agent/toolkit.py
- **chunk 3** (4 files): frontend/src/scenes/max/max-constants.tsx, frontend/src/queries/schema/schema-assistant-messages.ts, frontend/src/queries/schema.json, posthog/schema_enums.py

## Per-review-unit breakdown

| pass | chunk | perspective                                    | raw issues |
| ---- | ----- | ---------------------------------------------- | ---------- |
| 1    | 1     | review-hog-perspective-contracts-security      | 2          |
| 1    | 2     | review-hog-perspective-contracts-security      | 1          |
| 1    | 3     | ?                                              | 0          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 2     | ?                                              | 0          |
| 2    | 3     | ?                                              | 0          |
| 3    | 1     | review-hog-perspective-performance-reliability | 3          |
| 3    | 2     | review-hog-perspective-performance-reliability | 1          |
| 3    | 3     | ?                                              | 0          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] must_fix · security — ee/hogai/tools/actions/tool.py:69-73

**list_actions bypasses object-level access control (information disclosure)**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `ListActionsTool` enforces only the resource-level check declared in `get_required_resource_access()` (`[("action", "viewer")]`), then calls `list_actions` (core.py L142-166), which returns every non-deleted action in the team via `Action.objects.filter(team=team, deleted=False)` with no object-level access filtering. The REST `ActionViewSet.list` path filters its queryset through `user_access_control.filter_queryset_by_access_level(...)` (via `_filter_queryset_by_access_level` in `posthog/api/routing.py:368`), which excludes actions the requesting user is explicitly denied object-level access to (an `AccessControl` row with `access_level="none"` scoped to the user/role). The sibling `ListFeatureFlagsTool` follows exactly this pattern in `EntitySearchContext._list_feature_flags_sync` (`ee/hogai/context/entity_search/context.py:409`), whose comment explicitly notes that the resource-level gate alone does not prune object-level denials. As a result, on EE deployments with ACCESS_CONTROL enabled, a user with default resource-level "viewer" but an explicit object-level denial on a specific action can still read that action's name, description, and full step (trigger) definition through Max's `list_actions` — even though the companion `get_action` tool (whose object-level check was added in this same PR) now blocks reading that exact action via `check_object_access`. This inconsistency leaks the content of access-restricted actions through the list surface.
- **Suggestion:** Apply object-level filtering in the list path, mirroring `ListFeatureFlagsTool`. Thread the tool's `self.user_access_control` into `list_actions` and run the queryset through `filter_queryset_by_access_level` before search/pagination. For example, in `core.py`:

```python
def list_actions(team, user_access_control, search, limit, offset):
    qs = Action.objects.filter(team=team, deleted=False)
    qs = user_access_control.filter_queryset_by_access_level(qs)
    if search:
        qs = qs.filter(name__icontains=search)
    ...
```

and in `ListActionsTool._arun_impl`:

```python
result = await database_sync_to_async(list_actions)(
    self._team, self.user_access_control, search, limit, offset
)
```

`MaxTool.user_access_control` (ee/hogai/tool.py:128) is already available and `filter_queryset_by_access_level` is sync-safe inside `database_sync_to_async`. This brings `list_actions` in line with both the REST endpoint and the object-level checks already added to `get_action`/`update_action`/`delete_action` in this PR.

- **Validator:** The reported information disclosure requires an object-level AccessControl row with access_level="none" scoped to a specific action, but that state cannot exist. `minimum_access_level("action")` returns "viewer" (posthog/rbac/user_access_control.py:169), and `validate_access_level` (ee/api/rbac/access_control.py:107-112) rejects any access level below the resource minimum, so the API refuses to create a "none" ACL for an action. `filter_queryset_by_access_level` only blocks a resource_id whose explicit (role/member) access controls are all "none" (user_access_control.py:924-930) — a condition unreachable for actions. Actions are intentionally pinned to a "viewer" floor because insights and funnels must be able to read them, which is precisely why they diverge from feature flags. The sibling comparison to `ListFeatureFlagsTool` is a false equivalence: feature flags have a "none" minimum (they can be object-denied), actions do not. As a corollary, the `check_object_access(action, "viewer")` call added to `get_action` in this PR is itself a no-op for reads, so there is no real behavioral inconsistency between the get and list surfaces — neither can block a viewer-level read because no action can be object-denied. The finding is thorough in form but rests on a premise the system prevents by design, so it should be dropped.

### [✅ VALID] consider · bug — ee/hogai/tools/actions/core.py:147-150

**order_by("name") is not a stable total order, so offset pagination can skip or duplicate rows**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `list_actions` paginates with `qs.order_by("name")` followed by offset/limit slicing. `name` is nullable on the `Action` model (max_length=400, null=True, blank=True), and uniqueness is only enforced when a name is actually provided (`_check_name_available` skips blank names, and legacy/other-path actions may have NULL or duplicate names). When two rows share the same sort key, Postgres does not guarantee a stable order between them across separate queries, so consecutive `offset` pages (each a distinct query) can silently skip or repeat an action at the page boundary. The tool advertises stable pagination ("increase offset to N for the next page"), so a non-deterministic tiebreak undermines that contract for an agent paging through results.
- **Suggestion:** Add a unique, deterministic tiebreaker to the ordering, e.g. `qs.order_by("name", "id")`, so equal or NULL names still yield a stable total order across paginated calls.
- **Validator:** Confirmed against the model: `Action.name` is `null=True, blank=True` (products/actions/backend/models/action.py:43) and the model's `Meta` declares no default `ordering`, so `qs.order_by("name")` in `list_actions` is the sole sort key. Offset pagination across separate queries (each page is its own query) requires a stable _total_ order; when two rows share a sort key — duplicate names, or the multiple NULL-named actions that exist because the tool only enforces uniqueness on non-blank names it creates, while legacy/other-path actions can be NULL or duplicate — Postgres gives no guarantee of a consistent tiebreak between queries. The concrete consequence is a row silently skipped or repeated at a page boundary, which directly undermines the tool's advertised contract ('increase offset to N for the next page') for an agent paging through results. The trigger and consequence are both nameable and the fix is a trivial, low-risk one-liner (`order_by("name", "id")`). This is a genuine correctness defect, not speculative — appending a unique tiebreaker is the standard, well-established fix for offset pagination. Severity of 'consider' is appropriate: it only bites when duplicate/NULL names coexist with multi-page traversal, and the blast radius is a bounded (≤100) action list, so impact is real but minor.

### [✅ VALID] should_fix (validator→consider) · performance — ee/hogai/tools/actions/core.py:143-150

**list_actions fetches the unused bytecode JSONField for every listed action**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** `list_actions` loads full `Action` rows via `list(qs[start : start + capped_limit])` (up to MAX_LIST_LIMIT=100 rows), but the compact list rendering in `_format_action` only reads `id`, `name`, `description`, `steps` (steps_json) and `bytecode_error`. The `bytecode` JSONField — the compiled HogQL bytecode, which can be several KB per action — is pulled from Postgres and JSON-deserialized into Python for every row on every call, then discarded. This tool is explicitly designed for repeated, paginated calls by an LLM agent over projects that (per the tool's own description) 'can have thousands of actions', so the wasted I/O and deserialization compounds across pages and calls.
- **Suggestion:** Exclude the unused column: `qs = Action.objects.filter(team=team, deleted=False).defer("bytecode")` (or `.only("id", "name", "description", "steps_json", "bytecode_error")`). Keep the detailed get/create/update/delete paths as-is since they operate on a single row where the cost is negligible.
- **Validator:** The premise is factually correct: `list_actions` materializes full `Action` rows via `list(qs[...])`, and the list-path renderer `_format_action(a)` (non-detailed) only touches `id`, `name`, `description`, `action.steps` (which reads `steps_json`, action.py:121-122) and `bytecode_error`. The `bytecode` JSONField (action.py:54) — compiled HogQL bytecode, unrelated to the fields displayed — is fetched from Postgres and JSON-deserialized for every listed row and then discarded. So the wasted column is real and the suggested `.defer("bytecode")` / `.only(...)` fix is idiomatic, correct, and low-risk. However, the severity is overstated. This is not the 'bites at real scale' class the perspective implies: results are hard-capped at MAX_LIST_LIMIT=100 in a single query (no N+1, no unbounded scan), so the overhead is a bounded constant factor — one extra JSONField per row for at most 100 rows per call, roughly the same order as the `steps_json` payload that is legitimately loaded. It compounds only linearly with rows the agent actually pages through, which is inherent to listing. This is a legitimate, easily-fixed efficiency nit worth recording, but it does not meaningfully affect users at the level of a should_fix, so I'm lowering it to `consider`.

### [❌ dismissed] consider · performance — ee/hogai/tools/actions/core.py:147-150

**Offset pagination ordered by the unindexed name column scans and sorts the full set per call**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** `list_actions` orders by `name` (`qs.order_by("name")`) and paginates with OFFSET slicing (`qs[start : start + capped_limit]`). The only index on `Action` is `(team_id, -updated_at)`; `name` is unindexed, so each list call requires a full filesort of the team's filtered action set, and deep offsets force Postgres to scan-and-discard `start` rows. The tool's description advertises that projects 'can have thousands of actions' and encourages repeated paged calls, so on large projects every page pays the sort cost over the whole set. `name__icontains` search additionally can't use an index. This is bounded per team and consistent with existing behavior, so it's a scalability note rather than an outage risk.
- **Suggestion:** For large-project scalability, consider keyset/seek pagination over a stable, indexed ordering (e.g. order by `id` and page with `id > last_seen_id`) instead of OFFSET+unindexed-sort, or add an index covering the sort column if `name` ordering is required. At minimum, document that pagination cost grows with total action count so callers prefer `search` for lookups.
- **Validator:** The technical observations are accurate — `name` is unindexed (the only index is `(team_id, -updated_at)`, action.py:74), so `order_by("name")` requires a filesort and `name__icontains` can't use an index — but this does not clear the 'bites at real scale' bar. The result set is bounded per team, and Postgres sorting even several thousand short `name` strings after an indexed `team_id` filter is a sub-millisecond in-memory operation, not a hot-path problem: these list calls are triggered by an LLM agent at human/agent cadence, not per-request-per-row traffic, and each page is capped at 100. The OFFSET scan-and-discard cost is likewise trivial at these cardinalities. The reviewer itself concedes this is 'a scalability note rather than an outage risk.' The suggested remedies — migrating to keyset/seek pagination or adding an index for a column that sorts fine at realistic volumes — are exactly the speculative, future-proofing overengineering the validation bar says to drop: they solve a scale that isn't in scope and would rearchitect the tool's simple, working OFFSET pagination for no measurable user benefit. The genuinely worthwhile part of the ordering concern (a stable tiebreaker for correctness) is already captured by a separate finding; this performance framing adds no actionable, real-impact issue.

### [✅ VALID] should_fix · bug — ee/hogai/tools/actions/tool.py:69-73

**ListActionsTool crashes on negative limit/offset instead of failing gracefully**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** ListActionsTool.\_arun_impl forwards the LLM-supplied `limit` and `offset` straight into `list_actions`, which slices the queryset as `qs[start : start + capped_limit]` with `start = offset or 0` and `capped_limit = min(limit or DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT)` (core.py:148-150). The args schema `ListActionsToolArgs` (core.py:56-60) puts no lower bound on either field. A negative `offset` yields a negative slice start, and a negative `limit` makes `capped_limit` negative and thus a negative slice stop — either case triggers Django's `raise ValueError("Negative indexing is not supported.")` (confirmed in QuerySet.**getitem**). Unlike the sibling tools, `ListActionsTool._arun_impl` has no try/except and does not convert this into a `MaxToolRetryableError`. The raw ValueError propagates to the graph's generic handler (ee/hogai/core/agent_modes/executables.py:563), which treats unknown exceptions as fatal: the LLM is told "The tool raised an internal error. Do not immediately retry" and the failure is reported to error tracking via `capture_exception`. So a trivially-correctable bad input from the model becomes a non-retryable dead-end plus recurring exception noise, rather than the graceful "you may retry with adjusted inputs" path the other action tools already provide.
- **Suggestion:** Reject or clamp out-of-range pagination values before they reach the slice. Cleanest is to constrain the schema in core.py so Pydantic rejects them (a ValidationError IS handled gracefully at executables.py:545): `limit: Optional[int] = Field(default=None, ge=1, le=MAX_LIST_LIMIT, ...)` and `offset: Optional[int] = Field(default=None, ge=0, ...)`. Alternatively, clamp defensively inside `list_actions` — e.g. `start = max(offset or 0, 0)` and `capped_limit = min(max(limit or DEFAULT_LIST_LIMIT, 1), MAX_LIST_LIMIT)` — and/or wrap the `database_sync_to_async(list_actions)` call in `ListActionsTool._arun_impl` in the same `try/except ActionToolError -> MaxToolRetryableError` pattern used by the other tools so bad input surfaces as a retryable error instead of a captured internal exception.
- **Validator:** This is a genuinely reachable reliability gap. `ListActionsToolArgs` (core.py:56-60) puts no lower bound on `limit`/`offset`, and `list_actions` slices `qs[start : start + capped_limit]` with `start = offset or 0` and `capped_limit = min(limit or DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT)` (core.py:148-150). A negative `offset` (negative slice start) or negative `limit` (negative slice stop) triggers Django's `ValueError("Negative indexing is not supported.")`. Unlike the sibling action tools, `ListActionsTool._arun_impl` (tool.py:69-73) has no try/except, so the raw ValueError falls through to the generic `Exception` handler in executables.py:563-576, which tells the LLM "Do not immediately retry" and reports to error tracking via `capture_exception` — whereas a Pydantic `ValidationError` (executables.py:545) or `MaxToolRetryableError` would be handled gracefully. The input source is an LLM (genuinely uncontrolled), so a negative pagination value is plausible rather than impossible, and the code already handles the offset-beyond-total case gracefully — negative is simply a missed branch in otherwise deliberate input hygiene. The consequence (a trivially-correctable bad input becoming a non-retryable dead-end plus recurring exception noise) and trigger are both concrete, and the fix is trivial and matches the file's established pattern (add `ge`/`le` bounds to the schema so Pydantic rejects it gracefully). The should_fix severity is appropriate given low-but-real likelihood and bounded impact.
