# Reviewer-quality run — `C3-both-2`

- **Dumped:** 2026-07-01T23:39:14+00:00
- **Report id:** `019f1ff6-104c-710e-869b-d252f5fb11d1` · **PR:** https://github.com/PostHog/posthog/pull/62096
- **Head:** `ba725a897db35053525e5bdfac2c64a8b007fcb4` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 1503s (25.1 min)

## Config snapshot

- runtime / model / effort: `claude` / `claude-opus-4-8` / `xhigh`
- `EXPERIMENT_FORCE_CHUNKING` = True
- effective chunk target / soft-max additions = 250 / 400
- `EXPERIMENT_SEQUENTIAL_PERSPECTIVES` = True
- `EXPERIMENT_COMPLETENESS_PASS` = False

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 2      | 6            | 5          | 4           | 4                |

- **review units** = every (perspective|gap × chunk) sandbox review that ran = the model-held-constant cost proxy.
- **local `$ai_generation` tokens (best-effort, may be pre-ingestion / partial):**

  | model           | gens    | input tok    | output tok |
  | --------------- | ------- | ------------ | ---------- |
  | claude-opus-4-8 | 101     | 10587977     | 106351     |
  | **total**       | **101** | **10587977** | **106351** |

## Chunking

- **chunk 1** (5 files): ee/hogai/tools/actions/core.py, ee/hogai/tools/actions/tool.py, ee/hogai/tools/actions/**init**.py, ee/hogai/tools/**init**.py, ee/hogai/chat_agent/toolkit.py
- **chunk 2** (4 files): frontend/src/scenes/max/max-constants.tsx, frontend/src/queries/schema/schema-assistant-messages.ts, frontend/src/queries/schema.json, posthog/schema_enums.py

## Per-review-unit breakdown

| pass | chunk | perspective                                    | raw issues |
| ---- | ----- | ---------------------------------------------- | ---------- |
| 1    | 1     | review-hog-perspective-contracts-security      | 2          |
| 1    | 2     | ?                                              | 0          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 1          |
| 3    | 1     | review-hog-perspective-performance-reliability | 1          |
| 3    | 2     | ?                                              | 0          |

## Findings (post-dedup) with validator verdict

### [✅ VALID] must_fix · security — ee/hogai/tools/actions/core.py:142-166

**list_actions bypasses object-level access controls (data exposure)**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `list_actions` filters only by `team=team, deleted=False` (plus optional name search) and relies solely on the resource-level gate `get_required_resource_access() -> [("action", "viewer")]` declared on `ListActionsTool`. It never prunes actions the user is denied at the object level. The REST contract this PR intends to mirror does prune them: `ActionViewSet.list` runs the queryset through `TeamAndOrgViewSetMixin._filter_queryset_by_access_level`, which calls `user_access_control.filter_queryset_by_access_level(...)` for the `list` action (posthog/api/routing.py:368-388), removing objects with an explicit object-level `none` access control. The established in-product pattern `ee/hogai/context/entity_search/context.py::_list_feature_flags_sync` (lines 401-411) combines both gates: a resource-level `check_access_level_for_resource` AND `filter_queryset_by_access_level` for object-level pruning. Here only the resource-level half is present. Consequently a user with resource-level `action` viewer access but an explicit per-object `viewer`/`none` restriction on specific actions can still read those actions' names, descriptions, and full step definitions through Max's `list_actions`. This is the read/list counterpart of the update/delete object-level bypass that was already fixed for get/update/delete via `check_object_access` (tool.py:86,124,145,153) — the list path was missed, so the object-level ACL is enforced everywhere except when listing.
- **Suggestion:** Prune object-level denials on the list path, matching REST and the entity_search precedent. Thread the tool's `UserAccessControl` into `list_actions` (e.g. add a `user_access_control` parameter passed from `ListActionsTool._arun_impl` as `self.user_access_control`) and apply it to the queryset before counting/slicing:

```python
def list_actions(team, search, limit, offset, user_access_control):
    qs = Action.objects.filter(team=team, deleted=False)
    if search:
        qs = qs.filter(name__icontains=search)
    qs = user_access_control.filter_queryset_by_access_level(qs)
    total = qs.count()
    qs = qs.order_by("name")
    ...
```

Computing `total` after filtering keeps the "Showing X of Y" / pagination counts honest for the caller. This mirrors `_list_feature_flags_sync` and closes the gap so list is consistent with the object-level checks already added to get/update/delete.

- **Validator:** Confirmed real object-level access-control gap. `list_actions` (core.py:142-166) filters only by team/deleted/name and relies solely on the resource-level gate declared via `ListActionsTool.get_required_resource_access() -> [("action","viewer")]`; it never prunes objects the user is denied at the object level. That object-level layer is real and enforced everywhere else in this same toolset: GetActionTool, UpdateActionTool, and DeleteActionTool all call `self.check_object_access(action, ...)` (tool.py:86,124,145,153), which routes to `UserAccessControl.check_access_level_for_object`. The REST list path prunes these denials (routing.py `_filter_queryset_by_access_level` runs `filter_queryset_by_access_level` for the `list` action), and the in-product precedent `_list_feature_flags_sync` (context.py:401-417) explicitly combines the resource-level check with `filter_queryset_by_access_level`. Consequently a user with resource-level action viewer access but an explicit per-object `none` restriction on specific actions can still read those actions' names, descriptions, and full step definitions via `list_actions`. This is the list counterpart of the exact object-level bypass already fixed for get/update/delete in this PR — the list path was missed. The suggested fix (thread the tool's UserAccessControl into `list_actions`, apply `filter_queryset_by_access_level` before counting/slicing) is concrete, matches both the REST contract and the entity_search precedent, and keeps pagination counts honest. Named trigger and consequence are both concrete, so this clears the security bar. must_fix is appropriate given it is a deliberate-restriction bypass consistent with the checks the author already added elsewhere.

### [✅ VALID] should_fix · bug — ee/hogai/tools/actions/core.py:148-150

**list_actions does not validate negative limit/offset (contract divergence from REST)**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `ListActionsToolArgs.limit`/`offset` are typed `Optional[int]` with no lower bound, and `list_actions` uses them directly: `start = offset or 0` and `capped_limit = min(limit or DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT)`. Nothing rejects negative values. The REST list endpoint deliberately guards this via `ActionViewSet._parse_non_negative_int`, which returns `None` for any value `< 0` so negatives are treated as absent. Here a model-supplied negative `offset` (e.g. `-3`) yields the slice `qs[-3 : 22]`, and Django querysets do not support negative indexing, so this raises an unhandled exception inside `list_actions`. Because `ListActionsTool._arun_impl` does not wrap this in `MaxToolRetryableError` (and it wouldn't be an `ActionToolError` anyway), a hallucinated negative offset surfaces as a hard tool failure rather than a recoverable message. A negative `limit` similarly produces a nonsensical `min(-5, 100) = -5` slice bound. This is both an input-validation boundary gap and a divergence from the documented `1-{MAX_LIST_LIMIT}` / non-negative contract.
- **Suggestion:** Match the REST contract by clamping/validating non-negative bounds. Either add pydantic constraints on the args schema (`limit: Optional[int] = Field(default=None, ge=1, le=MAX_LIST_LIMIT)` and `offset: Optional[int] = Field(default=None, ge=0)`), or normalize inside `list_actions` (e.g. `start = max(offset or 0, 0)` and `capped_limit = min(max(limit or DEFAULT_LIST_LIMIT, 1), MAX_LIST_LIMIT)`). Schema-level constraints are preferable since they reject bad input before it reaches the ORM and are reflected in the tool's JSON schema shown to the model.
- **Validator:** Confirmed real, reachable boundary gap. `ListActionsToolArgs.limit`/`offset` (core.py:56-60) are `Optional[int]` with no `ge` constraint, and `list_actions` (core.py:148-150) uses them raw: `start = offset or 0`, `capped_limit = min(limit or DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT)`. A model-supplied negative `offset` (e.g. -3) yields `qs[-3:22]`; Django querysets do not support negative indexing and raise `ValueError`. A negative `limit` similarly yields a negative slice bound that raises. Crucially `ListActionsTool._arun_impl` (tool.py:69-73) has no try/except and this is not an `ActionToolError`, so it surfaces as a hard, unrecoverable tool failure rather than a retryable message the model could correct — unlike create/update/delete which wrap `ActionToolError` in `MaxToolRetryableError`. The REST endpoint deliberately guards this via `_parse_non_negative_int` (action.py:563, 600-601), treating negatives as absent, so the tool also diverges from the documented non-negative contract. The input source is a hallucinating LLM and the schema advertises but does not enforce the `1-100` range, so negative values are genuinely possible rather than adversarial-only. Fix is trivial (pydantic `ge=` constraints or clamping) and matches the existing REST behavior. should_fix is appropriate: robustness/contract gap producing an unhandled exception, not a security or data-loss issue.

### [✅ VALID] should_fix · bug — ee/hogai/tools/actions/core.py:147-150

**list_actions pagination is non-deterministic (order_by lacks a unique tie-breaker)**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `list_actions` orders the queryset with `qs.order_by("name")` and then slices it for offset-based pagination (`qs[start : start + capped_limit]`). `name` alone is not a total ordering: `Action.name` is `null=True`/`blank=True` (the code even renders `(unnamed)` for null names on line 125), so multiple actions can share the same sort key (all null-named actions, plus any duplicate names from legacy/bulk-imported data that predate the write-time uniqueness check). Postgres does not guarantee a stable relative order for rows with equal sort keys across separate queries, so the row order within a tie group can differ between calls. Unlike the REST list endpoint — which returns the full unpaginated list by default, so a single response is internally consistent — this tool is _always_ paginated (default limit 25) and its description explicitly instructs the model to walk pages with `offset`. Across those successive `list_actions(offset=0)`, `list_actions(offset=25)`, … calls, a tie straddling a page boundary can cause actions to be silently skipped or returned twice, so the agent can miss actions entirely or double-count them during discovery.
- **Suggestion:** Add a deterministic secondary sort key so the ordering is total and pagination is stable, e.g. `qs = qs.order_by("name", "id")` (or `"pk"`). `id` is unique and non-null, which fully breaks ties (including among null-named actions) and guarantees a consistent page sequence across offset calls.
- **Validator:** Technically correct and verified. `Action.name` is `null=True, blank=True` (action.py:43) and carries no DB uniqueness constraint — the tool's write-time `_check_name_available` only blocks new duplicates, while legacy data, bulk imports, and multiple null-named actions (the code itself renders '(unnamed)' at core.py:125) can share the `name` sort key. `list_actions` (core.py:147-150) orders solely by `order_by("name")` and then slices `qs[start : start + capped_limit]` for offset pagination. Postgres gives no stable relative order for rows with equal sort keys across separate queries, so a tie group straddling a page boundary can cause actions to be silently skipped or returned twice across successive `list_actions(offset=0/25/...)` calls. This is directly relevant because, unlike the REST endpoint (which returns the full unpaginated list by default, so a single response is internally consistent), this tool is always paginated and its own description instructs the model to page with `offset` — so the discovery loop is exactly where the instability bites, causing the agent to miss or double-count actions. The fix is a one-line, standard, uncontroversial `order_by("name", "id")` that makes the ordering total (id is unique/non-null, also breaking ties among null names). Real correctness impact for the tool's stated purpose plus a trivial, low-risk fix clears the bar. should_fix is appropriate — a correctness/reliability defect, not a security or data-loss issue.

### [✅ VALID] should_fix (validator→consider) · best_practice — ee/hogai/tools/actions/core.py:192-205,208-233

**Max action CRUD skips the report_user_action product-analytics events the REST path emits (observability gap)**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The REST write path instruments every action mutation with product-analytics events: ActionSerializer.create() emits report*user_action(..., "action created", instance.get_analytics_metadata(), ...) (products/actions/backend/api/action.py:249-255) and ActionSerializer.update() emits report_user_action(..., "action updated", ...) (lines 270-279). Because REST deletes are performed as a PATCH deleted=True through update() (the viewset inherits ForbidDestroyModel), even deletes emit an "action updated" event on the REST path. The Max tool core functions bypass the serializer and go straight through the Action model, so create_action (192-205), update_action (208-226), and delete_action (229-233) emit none of these events. Notably the PR deliberately ported the \_sibling* piece of REST telemetry — check*count_limit / "resource limit hit" (196-199) — which only fires at/above the 500-action soft cap, while dropping the create/update events that fire on every mutation. The net effect: actions created, updated, and deleted by Max are invisible to the product analytics that track action-mutation volume and metadata (step_count, match*\*\_count, etc.), so those metrics silently undercount as agent-driven CRUD grows into a first-class write surface. (Audit/attribution is still covered via the activity log through ModelActivityMixin + \_acting_user, so this is an analytics-observability gap, not an audit-trail gap.)
- **Suggestion:** Emit the same report_user_action events the REST serializer does, from the tool core functions where the acting user is already available. In create_action, after action.save(), call report_user_action(user, "action created", action.get_analytics_metadata(), team=team). In update_action, after save(), call report_user_action(user, "action updated", {\*\*action.get_analytics_metadata(), "updated_by_creator": user.id == action.created_by_id}). Consider an "action deleted"/"action updated" event in delete_action for parity with the REST PATCH-delete path. This keeps agent-driven action mutations visible in the same product-analytics stream as REST-driven ones. (report_user_action already swallows its own capture errors, so it won't add a failure path to the save; keep it after the successful save.)
- **Validator:** Verified divergence: REST ActionSerializer.create() (products/actions/backend/api/action.py:248-255) emits report_user_action(..., 'action created', instance.get_analytics_metadata(), ...) and update() (269-279) emits 'action updated'; REST deletes go through update() (ForbidDestroyModel PATCH deleted=True) so they too emit 'action updated'. The Max tool core functions bypass the serializer and go straight through the Action model, so create_action (core.py:192-205), update_action (208-226), and delete_action (229-233) emit none of these product-analytics events. The observation is accurate and reproducible, and the PR did port the sibling check_count_limit / 'resource limit hit' telemetry (196-199) while dropping these. However, this is not a correctness, security, data-loss, contract, or reliability defect — the reviewer explicitly scopes it as analytics-observability only, and audit/attribution is fully preserved via ModelActivityMixin +\_acting_user. The impact is internal product-analytics undercounting of action-mutation volume as agent CRUD grows, with no user-facing or data-integrity consequence. It is also genuinely debatable whether agent-driven mutations should be merged into the same 'action created'/'action updated' events as human CRUD — doing so could pollute human-usage metrics rather than improve them — so the proposed fix is a product/design call rather than a clear defect. Real but minor and non-functional: kept on record and soft-suppressed to consider rather than surfaced as a should_fix.
