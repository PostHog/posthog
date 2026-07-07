# Reviewer-quality run — `m1-t2-smoke-run3`

- **Dumped:** 2026-07-06T23:58:09+00:00
- **Report id:** `019f39c2-7003-740d-8629-756fb5d03aa5` · **PR:** https://github.com/PostHog/posthog/pull/62096
- **Head:** `ba725a897db35053525e5bdfac2c64a8b007fcb4` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 1830s (30.5 min)

## Config snapshot

- runtime / model / effort: `claude` / `claude-sonnet-5` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 2      | 8            | 10         | 9           | 7                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.

### Cache-aware spend (local `$ai_generation`, best-effort)

| model           | stage      | gens    | fresh in    | cache write   | cache read     | output      | >200K gens | true $     | gw $       |
| --------------- | ---------- | ------- | ----------- | ------------- | -------------- | ----------- | ---------- | ---------- | ---------- |
| claude-sonnet-5 | review     | 173     | 108,987     | 1,068,966     | 17,617,744     | 123,542     | 3          | $7.65      | $7.65      |
| claude-opus-4-8 | validation | 47      | 30,895      | 173,801       | 3,567,390      | 50,874      | 0          | $4.30      | $4.30      |
| claude-sonnet-5 | blind-spot | 86      | 37,380      | 332,763       | 9,809,858      | 55,187      | 0          | $3.42      | $3.42      |
| claude-sonnet-5 | chunking   | 1       | 52,552      | 0             | 0              | 5,882       | 0          | $0.16      | $0.16      |
| claude-sonnet-5 | dedup      | 1       | 45,971      | 0             | 0              | 4,456       | 0          | $0.14      | $0.14      |
| **total**       |            | **308** | **275,785** | **1,575,530** | **30,994,992** | **239,941** | **3**      | **$15.67** | **$15.67** |

- `true $` = list-price back-calc (fresh 1× + cache write 1.25× + cache read 0.1× + output); `gw $` = gateway `$ai_total_cost_usd` (LiteLLM). Δ (priced buckets) = +0.0%.
- naive method (all prompt tokens at input price): $80.17 — 5.1× the true cost; never gate on it.
- gateway per-side cross-check (gens emitting the field; LiteLLM's `input_cost` is the whole input side, cache included):
  - input side (fresh + cache write + cache read): $12.5040 over 308 gen(s) (true $12.5040, Δ +0.0%)
  - · of which cache read: $7.2692 over 300 gen(s) (true $7.2692, Δ +0.0%)
  - · of which cache write: $4.5906 over 306 gen(s) (true $4.5906, Δ +0.0%)
  - · of which fresh (derived): $0.6443 over 308 gen(s) (true $0.6443, Δ +0.0%)
  - output: $3.1625 over 308 gen(s) (true $3.1625, Δ -0.0%)
- 3 gen(s) ran with >200K-token prompts; the gateway map prices these models flat, so no long-context premium is included in either column.

### Turn-1 cache reads per sandbox unit (cross-sandbox sharing tripwire)

| unit      | stage      | first gen | t1 cache read | t1 cache write |
| --------- | ---------- | --------- | ------------- | -------------- |
| …f9b5ecb2 | review     | 23:30:01  | 0             | 55,807         |
| …8e52c5c8 | review     | 23:30:02  | 0             | 95,418         |
| …c2cda968 | review     | 23:30:04  | 37,120        | 58,299         |
| …e9769ff9 | review     | 23:30:04  | 0             | 95,419         |
| …350576b8 | review     | 23:30:04  | 37,120        | 18,687         |
| …46a74994 | review     | 23:30:05  | 37,120        | 18,686         |
| …2b87d01c | blind-spot | 23:37:48  | 37,120        | 20,714         |
| …0167fc8e | blind-spot | 23:37:52  | 37,120        | 62,919         |
| …9bd58c8a | validation | 23:46:42  | 0             | 38,227         |
| …51301228 | validation | 23:46:45  | 24,755        | 13,892         |

- units with turn-1 cache_read > 0: **6/10** (report the distribution, not a median).

## Chunking

- **chunk 1** (5 files): ee/hogai/tools/actions/core.py, ee/hogai/tools/actions/tool.py, ee/hogai/tools/actions/**init**.py, ee/hogai/tools/**init**.py, ee/hogai/chat_agent/toolkit.py
- **chunk 2** (4 files): frontend/src/queries/schema/schema-assistant-messages.ts, frontend/src/queries/schema.json, posthog/schema_enums.py, frontend/src/scenes/max/max-constants.tsx

## Per-review-unit breakdown

| pass | chunk | perspective                                    | raw issues |
| ---- | ----- | ---------------------------------------------- | ---------- |
| 1    | 1     | review-hog-perspective-contracts-security      | 2          |
| 1    | 2     | ?                                              | 0          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 2          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |
| 3    | 2     | review-hog-perspective-performance-reliability | 1          |
| 1000 | 1     | review-hog-blind-spots-general                 | 1          |
| 1000 | 2     | ?                                              | 0          |

## Findings (post-dedup) with validator verdict

### [✅ VALID] should_fix (validator→consider) · best_practice — ee/hogai/tools/actions/core.py:67-83

**CreateActionToolArgs.name / UpdateActionToolArgs.name have no max_length, unlike ActionSerializer, so an overlong name raises a raw DB error instead of a graceful ActionToolError**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `Action.name` is `models.CharField(max_length=400, null=True, blank=True)` (products/actions/backend/models/action.py line 43), backed by a `varchar(400)` Postgres column that hard-errors on insert/update if the value exceeds 400 characters. The REST path is protected against this: DRF's `HyperlinkedModelSerializer` auto-derives a `max_length=400` validator for the `name` field from the model, so an overlong name is rejected with a clean 400 validation error before it ever reaches the database. The Max tool schemas in this file — `CreateActionToolArgs.name: str = Field(description=...)` (line 68) and `UpdateActionToolArgs.name: Optional[str] = Field(default=None, description=...)` (line 78) — have no equivalent `max_length` constraint. An LLM-supplied name longer than 400 characters passes pydantic validation, passes `_check_name_available` (which only checks blank/duplicate), and then fails inside `action.save()` with an unhandled `django.db.utils.DataError` ('value too long for type character varying(400)') rather than the `ActionToolError` → `MaxToolRetryableError` path the rest of this module uses for user-fixable input problems. That surfaces as an unhandled internal error instead of a message the agent can react to and retry with a shorter name.
- **Suggestion:** Add `max_length=400` to both `name` fields to match the model and mirror what DRF derives automatically, e.g. `name: str = Field(max_length=400, description="Name of the action (must be unique within the project).")` on `CreateActionToolArgs` and the equivalent `Optional[str] = Field(default=None, max_length=400, description=...)` on `UpdateActionToolArgs`. Pydantic will then reject an overlong name at the tool-input boundary with a normal validation error surfaced back to the agent, consistent with how `_check_name_available` already surfaces blank/duplicate names as retryable errors.
- **Validator:** The premise checks out: Action.name is varchar(400) (products/actions/backend/models/action.py:43), Action.save() calls super().save() without full_clean() (action.py:80-82) so Django does not enforce max_length before the DB write, and neither the pydantic tool schemas nor \_check_name_available (core.py:181-189) constrain name length. A name >400 chars therefore reaches action.save() and raises django.db.utils.DataError, which the `except ActionToolError` handlers in tool.py do not catch. However, the impact is milder than the title implies: the error is not truly unhandled — the graph executor's generic catch-all (ee/hogai/core/agent_modes/executables.py:563) intercepts it, fires capture_exception (error-tracking noise for a user-fixable input), and returns a 'tool raised an internal error, do not immediately retry' message, instead of the clean, retryable ValidationError the pydantic path would produce (line 545). The real delta is thus modest, and the trigger — an LLM emitting a 400+ character action name — is a rare edge case since action names are short by convention. It is nonetheless a genuine consistency gap (the module already surfaces blank/duplicate names as retryable errors, and the REST path rejects overlong names via DRF's model-derived max_length) with a one-token fix that isn't overengineering. Keeping it on record as real-but-minor, but lowering severity: the low likelihood and low blast radius (no data loss, corruption, or security impact; failure is gracefully contained) don't justify surfacing it at should_fix.

### [✅ VALID] must_fix · security — ee/hogai/tools/actions/core.py:142-166

**list_actions bypasses object-level access control filtering (unlike ActionViewSet.list() and the established ListFeatureFlagsTool pattern)**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** list_actions(team, search, limit, offset) queries `Action.objects.filter(team=team, deleted=False)` with only a team scope — it never receives the acting user, so it cannot apply any per-object AccessControl filtering. ListActionsTool.get_required_resource_access() only checks resource-level 'viewer' access on 'action' (ee/hogai/tools/actions/tool.py lines 61-73), and ListActionsTool.\_arun_impl calls `list_actions(self._team, search, limit, offset)` without ever passing self.\_user or self.user_access_control. This is a real regression relative to the REST path: ActionViewSet.list() goes through TeamAndOrgViewSetMixin.get_queryset() → \_filter_queryset_by_access_level() → UserAccessControl.filter_queryset_by_access_level(), which excludes any action that has an explicit per-object AccessControl row denying the requesting user/role access — even when they have general resource-level 'viewer'/'editor' access to the 'action' resource type. The same PR round already fixed this exact class of gap for GetActionTool/UpdateActionTool/DeleteActionTool by adding `check_object_access(...)` before operating on a single action, but list_actions was missed. There is also a directly analogous, already-shipped precedent in this very codebase: ListFeatureFlagsTool → EntitySearchContext.list_feature_flags() explicitly calls `self.user_access_control.filter_queryset_by_access_level(queryset)` before returning results (ee/hogai/context/entity_search/context.py line ~409). Confirmed by the test suite too: ee/hogai/tools/actions/test/test_action_tools.py has `test_update_denied_by_object_level_access` patching `check_access_level_for_object` to verify UpdateActionTool is blocked, but there is no equivalent test for ListActionsTool — a user who has been explicitly restricted (via a per-object AccessControl row set to 'none') from viewing a specific sensitive action can still see its name, description, and step summary (and it still counts toward the 'Showing X of Y' total, leaking its existence) through list_actions, even though the same action is correctly hidden from them in the REST actions list and from direct get_action.
- **Suggestion:** Thread the acting user through to list_actions and apply the same object-level filtering the REST path and ListFeatureFlagsTool use. For example, change the signature to `list_actions(team: Team, user: User, search: Optional[str], limit: Optional[int], offset: Optional[int])`, build the base queryset as today, then before slicing add: `from posthog.rbac.user_access_control import UserAccessControl; uac = UserAccessControl(user=user, team=team, organization_id=str(team.organization_id)); qs = uac.filter_queryset_by_access_level(qs)` — computing `total` from the filtered queryset. Update ListActionsTool.\_arun_impl (ee/hogai/tools/actions/tool.py) to pass `self._user` (or reuse `self.user_access_control`, already available on MaxTool) into the call. Since `filter_queryset_by_access_level` does synchronous ORM work, keep it inside the `database_sync_to_async(list_actions)(...)` call as today.
- **Validator:** Confirmed genuine object-level access-control bypass. list_actions (core.py:142-166) filters only by team and never receives the acting user, so it skips the per-object AccessControl pruning that the REST path applies: ActionViewSet has scope_object='action' and TeamAndOrgViewSetMixin.get_queryset() runs_filter_queryset_by_access_level() → user_access_control.filter_queryset_by_access_level() specifically for the list action (routing.py:362,368-388). 'action' is a registered object-level resource (ACCESS_CONTROL_RESOURCES, user_access_control.py:59), and filter_queryset_by_access_level excludes explicitly-blocked objects even when the user has resource-level access (line 940-945). The sibling tools were hardened in the same PR round (GetActionTool/UpdateActionTool/DeleteActionTool call check_object_access — tool.py:86,124,145,153) but ListActionsTool.\_arun_impl was missed, and there is a direct in-repo precedent that does it correctly (ListFeatureFlagsTool via \_list_feature_flags_sync, context.py:406-411). Consequence: a user explicitly restricted from a specific action via a per-object 'none' AccessControl row can still see that action's name, description, and full step summary (event/url/selector/text/href/property conditions, all emitted by \_format_action non-detailed) and its existence via the 'Showing X of Y' total through list_actions, even though REST list and get_action correctly hide it. This is a concrete permission gap / information disclosure for the exact customers who configured object-level restrictions. The proposed fix (thread the user through and apply filter_queryset_by_access_level, plus the resource-level gate like list_feature_flags) is correct and matches the established pattern.

### [✅ VALID] should_fix (validator→consider) · bug — ee/hogai/tools/actions/core.py:51-60,142-150

**list_actions has no validation on limit/offset — negative values crash, limit=0 silently becomes the default**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `ListActionsToolArgs.limit`/`offset` (lines 56-60) are plain `Optional[int]` with no `ge`/`le` constraint, and nothing between the LLM-controlled tool args and `list_actions` (core.py:142) validates or clamps them. Two concrete failure modes result from `start = offset or 0` (line 148) and `capped_limit = min(limit or DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT)` (line 149) feeding directly into `qs[start : start + capped_limit]` (line 150):

1. Passing a negative `offset` or `limit` (e.g. `offset=-3` or `limit=-5`) produces a negative slice bound. Django's `QuerySet.__getitem__` raises `ValueError: Negative indexing is not supported.` for any negative start/stop — this exception is not caught anywhere in `list_actions` or in `ListActionsTool._arun_impl` (tool.py:69-73), so it propagates as an unhandled exception instead of the graceful `ActionToolError`/`MaxToolRetryableError` this codebase otherwise uses for all other bad-input cases.
2. Passing `limit=0` explicitly (a reasonable way for an agent to ask "just tell me the total count, no rows") silently falls back to the default of 25 because `0 or DEFAULT_LIST_LIMIT` evaluates the `0` as falsy — the caller's explicit `0` is discarded without any indication that the value was overridden.

The codebase already has a documented fix for exactly this class of problem: `ActionViewSet._parse_non_negative_int` (products/actions/backend/api/action.py:562-570) parses and clamps `offset`/`limit` from REST query params, returning `None` for negative values so they fall back to defaults instead of reaching a queryset slice. `list_actions` reimplements REST-equivalent pagination but omits this guard.

- **Suggestion:** Reject or clamp negative values before slicing, and distinguish `limit=0` from `limit=None`. For example:

```python
def list_actions(team: Team, search: Optional[str], limit: Optional[int], offset: Optional[int]) -> str:
    if limit is not None and limit < 0:
        raise ActionToolError("limit must be zero or a positive integer.")
    if offset is not None and offset < 0:
        raise ActionToolError("offset must be zero or a positive integer.")
    ...
    start = offset if offset is not None else 0
    capped_limit = min(limit, MAX_LIST_LIMIT) if limit is not None else DEFAULT_LIST_LIMIT
```

This surfaces bad input as the same `ActionToolError` → `MaxToolRetryableError` path already used elsewhere in this file, rather than an unhandled `ValueError`, and lets `limit=0` behave as the caller intended.

- **Validator:** Premise verified: ListActionsToolArgs.limit/offset are unconstrained Optional[int] (core.py:56-60), and start=offset or 0 / capped_limit=min(limit or DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT) feed qs[start:start+capped_limit] (core.py:148-150). A negative offset (start<0) or a negative limit that makes stop<0 triggers Django's ValueError: Negative indexing is not supported, which is not caught in list_actions or_arun_impl. limit=0 does silently become 25 via '0 or DEFAULT_LIST_LIMIT'. The REST path guards this with_parse_non_negative_int (action.py:562-570), so there is a genuine inconsistency. However, severity is lower than flagged: the ValueError is not an uncaught crash — the graph executor's generic except Exception (ee/hogai/core/agent_modes/executables.py:563) catches it, captures it to error tracking, and returns an 'internal error, do not immediately retry' message, so the practical delta of the fix is a clean retryable message vs. error-tracking noise. Likelihood is low: the limit field description explicitly steers the LLM to '1-100, default 25' and offsets come from the tool's own next-page hints, so negative pagination values are uncommon (the only semi-plausible trigger is a backward-pagination offset going negative). The limit=0 sub-case is contrived and harmless since the total is shown in the header regardless. This mirrors the earlier max_length finding — a real robustness gap in new code with a trivial fix and REST precedent, but low likelihood and impact contained by the catch-all. Keeping it on record but lowering from should_fix to consider per precision-over-recall.

### [✅ VALID] should_fix (validator→consider) · bug — ee/hogai/tools/actions/core.py:181-189,192-205,208-226

**Action names aren't stripped before uniqueness checks or persistence, unlike the REST path**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `_check_name_available` (lines 181-189) only uses `name.strip()` for the blank check on line 182, then queries `Action.objects.filter(team_id=team_id, name=name, deleted=False)` on line 184 using the raw, unstripped `name`. `create_action` (line 200: `Action(team=team, name=name, ...)`) and `update_action` (line 219: `action.name = name`) likewise persist the raw, unstripped value.

This diverges from the REST path: `ActionSerializer`'s auto-generated `name` field is a DRF `CharField` with default `trim_whitespace=True` (no `trim_whitespace=False` override in `products/actions/backend/api/action.py`), so by the time REST's `validate()`/`create()`/`update()` run, the name has already been stripped by DRF's `to_internal_value`.

Concretely, calling `create_action(..., name="Signup ")` (trailing space) when an action named `"Signup"` already exists in the same project:

- Passes the blank check (`"Signup ".strip()` is truthy).
- The exact-match filter `name="Signup "` does not match the existing `"Signup"` row, so the duplicate-name check silently misses the collision.
- The new action is saved with the trailing space intact (`name="Signup "`), producing two visually-identical actions that a human (or the REST UI, which does strip on save) would never be able to create side by side.
- **Suggestion:** Strip the name once and use the stripped value consistently for both the emptiness check and the persisted/queried value:

```python
def _check_name_available(team_id: int, name: str, *, exclude_id: Optional[int] = None) -> None:
    name = name.strip()
    if not name:
        raise ActionToolError("Action name may not be blank.")
    clash = Action.objects.filter(team_id=team_id, name=name, deleted=False)
    ...
```

and have `create_action`/`update_action` assign `action.name = name.strip()` (or have `_check_name_available` return the normalized name for the caller to use), matching DRF's implicit trimming behavior on the REST path.

- **Validator:** Premise verified. The REST path strips the name: the action 'name' field is auto-generated from the model CharField (not explicitly declared) so it inherits DRF's default trim_whitespace=True — the trim_whitespace=False overrides at action.py:72/90/96/108 are on the step subfields, not name — meaning attrs['name'] is already trimmed before ActionSerializer.validate() runs its uniqueness check (action.py:222-232) and before create/update persist. The tool path does not strip: \_check_name_available (core.py:181-189) calls name.strip() only for the blank check but queries filter(name=name) with the raw value, and create_action (core.py:200) / update_action (core.py:219) persist the raw value. So create_action(name='Signup ') when 'Signup' exists passes the blank check, misses the collision (exact-match query on 'Signup ' != 'Signup'), and saves a second visually-identical action with a trailing space — a real divergence, plus an internal inconsistency (already stripping for blank check but not elsewhere). However impact is minor: no data loss, corruption, security, or crash — just a cosmetic data-quality outcome (near-duplicate actions, stray whitespace), recoverable by rename/delete; and actions have no DB uniqueness constraint, so the defeated invariant is soft/application-level. Likelihood is moderate-low (whitespace in LLM-generated names is uncommon). This is the same 'diverges from REST on an uncommon input, cosmetic impact, trivial fix' shape as the other logic findings in this chunk; consistent with those and precision-over-recall, keeping on record but lowering from should_fix to consider.

### [✅ VALID] should_fix (validator→consider) · code_quality — frontend/src/scenes/max/max-constants.tsx:207-217

**update_action's nameArgKey binds to an optional field, silently dropping context on the common update-without-rename path**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `update_action`'s `displayFormatter` sets `nameArgKey: 'name'`, but the backend `UpdateActionToolArgs` (ee/hogai/tools/actions/core.py:76-83) defines `name: Optional[str] = None` — the identifier the LLM must always supply is `action_id: int`, not `name`. The backend's own `update_action()` function (core.py:208-226) explicitly supports and documents updating only `description` or only `steps` while omitting `name` (there's even a dedicated 'Nothing to update' branch for when all three are None). In that very common path, `skillStatusFormatter` (max-constants.tsx:163-173) resolves `rawName` to `undefined`, so the suffix is silently dropped and the chat UI just shows the generic 'Updating action...'/'Updated action' with no indication of which action is being changed. Compare with the sibling pair `update_llm_skill` (max-constants.tsx:1350-1361), which correctly keys `nameArgKey` off `skill_name` — the field that's always present because it identifies the target — rather than off a mutable, optional value. `update_action` is the only CRUD-update tool definition in this file whose `nameArgKey` points at an optional argument instead of the tool's required identifier.
- **Suggestion:** Key the update_action status label off the always-present `action_id` instead of the optional `name`, e.g. by extending `skillStatusFormatter` to accept a numeric identifier key (see the related consider-level finding on get_action/delete_action) or by having the tool call surface `action_id` under a string-friendly key. At minimum, this keeps the pending/completed status informative even when the LLM updates only `steps`/`description`, matching the precedent set by `update_llm_skill`.
- **Validator:** The premise is factually accurate: update_action sets nameArgKey: 'name' (max-constants.tsx:215), but the backend UpdateActionToolArgs makes name Optional[str]=None with action_id:int as the required identifier (core.py:76-83), and update_action() explicitly supports updating only description/steps via a dedicated 'Nothing to update' branch (core.py:215-226). On that path skillStatusFormatter (max-constants.tsx:167-172) resolves rawName to undefined and drops the suffix. However, the impact is purely cosmetic and degrades gracefully — the chat still shows a correct, coherent label ('Updating action...'), it just omits the name suffix in the update-without-rename case. No wrong data is shown, no logic breaks, nothing is mishandled; this is not a correctness/security/data/perf/reliability defect. The cited update_llm_skill parallel is also imperfect: skills are keyed by an always-present string skill_name, whereas actions are keyed by a numeric action_id, so there is no always-present string 'name' to key off, and the suggested fix (surfacing action_id, e.g. 'Updating action "42"') adds marginal value over the generic label. This is a real but minor UX-polish gap, not a should_fix bug — appropriate to keep on record at consider rather than surface prominently.

### [✅ VALID] consider · code_quality — frontend/src/scenes/max/max-constants.tsx:186-195,218-227

**get_action and delete_action surface no identifier for which action is being acted on**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `get_action` and `delete_action` set no `nameArgKey`, so their chat-status labels are the fully generic 'Getting action...'/'Deleting action...' with no indication of which action (by ID or name) is being targeted. This is a real gap because these tools' only identifying argument, `action_id` (ee/hogai/tools/actions/core.py:63-64, 86-87), is an `int`, and `skillStatusFormatter`'s `typeof rawName === 'string'` guard (max-constants.tsx:168) would suppress it even if wired up via `nameArgKey`. Sibling read/delete-style tools such as `get_llm_skill` (nameArgKey: 'skill_name') and `get_llm_skill_file` (nameArgKey: 'file_path') do surface a string identifier for the entity being acted on, so a user reviewing the Max chat transcript can tell which action is being fetched or deleted, whereas for `get_action`/`delete_action` it's ambiguous when multiple action tool calls happen in sequence.
- **Suggestion:** Extend `skillStatusFormatter` (or add a parallel numeric-safe helper) to also accept a numeric identifier — e.g. an `idArgKey` option that formats as `#${id}` when the arg is a number — and wire `get_action`/`delete_action` (and `update_action`, per the related finding) to use `action_id` via that mechanism so the status text always identifies which action is being operated on.
- **Validator:** The premise is factually accurate: get_action (max-constants.tsx:186-195) and delete_action (218-227) set no nameArgKey, so their status labels are the generic 'Getting action...'/'Deleting action...'; their only identifier is action_id:int (core.py:63-64, 86-87); and skillStatusFormatter's typeof rawName === 'string' guard (max-constants.tsx:168) would suppress a numeric value even if wired up, so a numeric-safe helper would indeed be needed. However, the impact is purely cosmetic and degrades gracefully — the labels remain correct and coherent, just without an identifier suffix. No wrong data is shown and no logic breaks; this is not a correctness/security/data/perf/reliability defect. The fix's only benefit is disambiguating sequential action calls by surfacing a bare numeric id (e.g. '#42'), which is marginal since a transcript reader does not inherently know which action that id maps to. This is a real-but-minor UX-polish item, correctly rated at 'consider' by the reviewer — kept on record but not surfaced prominently. No priority adjustment needed.

### [❌ dismissed] consider · performance — ee/hogai/tools/actions/core.py:142-166

**list_actions sorts/filters without a supporting index, so cost grows with team size on every call**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** `list_actions` filters by `team=team, deleted=False`, optionally by `name__icontains=search`, then does `qs.order_by("name")` before OFFSET/LIMIT slicing. The `Action` model (`products/actions/backend/models/action.py`) only declares `models.Index(fields=["team_id", "-updated_at"])` — there is no index covering `deleted`, `name`, or the `(team_id, name)` pair used here, so both the `qs.count()` and the ordered slice require scanning/sorting all of a team's non-deleted actions on every single call. The tool's own description explicitly says "Projects can have thousands of actions" and instructs the agent to page with `limit`/`offset` rather than fetch everything — but each subsequent page still re-executes the same full scan/sort plus a fresh `COUNT(*)`, and OFFSET-based pagination gets linearly more expensive as the agent increases `offset` to page deeper. This is a new, LLM-driven access pattern (an agent iterating pages in a single conversation turn) that can exercise this far more repetitively than a human clicking through the REST-backed UI.
- **Suggestion:** If large teams are an expected use case (as the docstring implies), consider adding a composite index such as `models.Index(fields=["team_id", "deleted", "name"])` to back both the filter and the `order_by("name")`, and/or switch to keyset pagination (e.g. `name > last_seen_name` instead of numeric `offset`) to avoid the O(offset) cost of deep pages. At minimum, this is worth flagging to the team since it mirrors a pre-existing gap in the REST path but is now exercised by a new, more repetitive caller.
- **Validator:** Premise is technically correct — Action only has Index(fields=['team_id', '-updated_at']) (action.py:74), so the team_id+deleted filter and order_by('name') in list_actions are not fully index-covered — but it does not meet the 'bites at real scale' bar. Per-team action count is effectively bounded: MAX_ACTIONS_PER_TEAM defaults to 500 (resource_limits/registry.py:71-75), so the realistic working set is hundreds of rows, not the 'thousands' the docstring loosely implies. The existing (team_id, -updated_at) index already narrows the scan to a single team's rows via its prefix; the residual cost is a deleted filter plus a name sort over a few hundred rows, which Postgres does in sub-millisecond-to-low-ms time — no user-visible impact. list_actions is a low-frequency LLM tool, not a high-QPS hot path, and OFFSET paging is bounded by the ~500-row total so it can never grow expensive. It also mirrors the pre-existing, accepted ActionViewSet.list() pattern (same filter+sort, no such index) rather than introducing a regression; the 'LLM pages more repetitively' claim is speculative. The proposed remedy (a new composite index — a migration with write-amplification and storage cost — plus a switch to keyset pagination) is overengineering for a bounded, infrequent caller. This falls in the drop buckets: speculative what-if over a dataset that can't reach problem scale, with an overengineered fix for a case not in scope. Dropping.

### [❌ dismissed] consider · performance — frontend/src/scenes/max/max-constants.tsx:176-227,1531-1543

**New tool entries grow an already O(n) per-render lookup rebuilt on every tool-call render**  
_perspective: review-hog-perspective-performance-reliability · directly-related: False_

- **Problem:** The five new entries added to `TOOL_DEFINITIONS` (list_actions, get_action, create_action, update_action, delete_action) push the record to roughly 100 top-level tool definitions (plus ~15 more nested under `subtools`). `getToolDefinition()` (max-constants.tsx:1531-1543) rebuilds a fully-flattened array of every tool/subtool from scratch — via `Object.entries(...).flatMap(...)` with object spreads for each entry — on every single call, and it is not memoized. `getToolDefinitionFromToolCall` (which wraps it) is invoked once per rendered tool call inside `ToolCallsAnswer` in `frontend/src/scenes/max/Thread.tsx` (`regularToolCalls.map(...)` around line 1268), which itself re-renders on every streamed token/update while Max is actively responding. That means each streaming update re-triggers, for every visible tool call in the thread, a full re-flatten-and-clone of the entire (now ~115-entry) tool catalog. This growing map is a pre-existing pattern this chunk directly extends, and it compounds with every future tool addition.
- **Suggestion:** Since this perspective's chunk is purely additive to `TOOL_DEFINITIONS`, no code change is strictly required here, but it's worth flagging now while the map is still growing: memoize the flattened lookup once at module load (e.g. build a `Map<string, ToolDefinition>` alongside `TOOL_DEFINITIONS` instead of recomputing it inside `getToolDefinition` on every call), so future tool additions (like these five) don't keep adding cost to a hot render path.
- **Validator:** The premise is factually accurate: getToolDefinition (max-constants.tsx:1531-1543) rebuilds a flattened array via Object.entries(...).flatMap(...) with spreads plus a linear .find on every call, unmemoized, and is invoked per rendered tool call in ToolCallsAnswer (Thread.tsx:1268) which re-renders during streaming. But the magnitude does not clear the bar. TOOL_DEFINITIONS is a static compile-time constant (~115 entries) that does not grow with user input or data — only with future code additions, which is slow and bounded. Rebuilding a ~115-element array of small objects and a linear find is microsecond-scale; even across dozens of visible tool calls at a high streaming rate it is negligible versus the React reconciliation and markdown re-rendering happening on the same path. This is not an N+1 query, unbounded loop, quadratic blowup, missing index, or blocking I/O. This PR adds only 5 entries to an already ~110-entry map, so it does not meaningfully change the characteristics, and the reviewer concedes no code change is strictly required and marks it not directly related to the changes. Per the criteria this is a speculative micro-optimization / future-proofing of a code path that is not a real bottleneck. Memoizing into a Map would be a minor code-quality nicety but is not a real performance defect worth surfacing. Precision over recall: drop.

### [✅ VALID] should_fix · best_practice — ee/hogai/tools/actions/core.py:192-205,208-226,229-233

**create_action/update_action/delete_action never emit the "action created"/"action updated" product-analytics events the REST path fires on every write**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** ActionSerializer.create() (products/actions/backend/api/action.py:236-256) calls `report_user_action(user, "action created", {**instance.get_analytics_metadata(), "creation_context": creation_context}, team=instance.team, request=...)` after every REST create, and ActionSerializer.update() (same file, lines 259-280) calls `report_user_action(user, "action updated", {**instance.get_analytics_metadata(), "updated_by_creator": ...}, team=instance.team, request=...)` after every REST update. Because the REST API forbids raw DELETE (`ForbidDestroyModel`), soft-delete on the REST path is performed via a PATCH that sets `deleted=True`, so it also flows through `update()` and fires the same "action updated" event (whose payload includes `deleted: True` via `get_analytics_metadata()`).

`create_action`, `update_action`, and `delete_action` in this file replicate the REST create/update/soft-delete behavior for bytecode compilation, activity logging, and even the resource-limit notification (`check_count_limit` — explicitly called out in the PR description as matching REST parity), but never call `report_user_action` for the create/update/delete case itself. `report_user_action` doesn't require a DRF `request` — it accepts `team`/`organization` kwargs directly (posthog/event_usage.py:392-401), exactly like `check_count_limit` is already invoked here, so there's no structural reason this was skipped other than an oversight.

Concretely: every action created, edited, or deleted through Max is invisible to whatever consumes the "action created"/"action updated" event stream (PostHog's own dogfooded product-usage analytics for the Actions feature), while the exact same operations performed via the REST UI or API are tracked. This silently breaks feature-adoption/usage visibility for an entire new creation surface (the AI assistant) without any error or test failure — the existing test suite for this PR (test_action_tools.py) doesn't assert on `report_user_action` calls, so this gap has no coverage on either side.

- **Suggestion:** Call `report_user_action` in `create_action` and `update_action` (and in the soft-delete branch, since delete goes through the same event name on REST) using `Action.get_analytics_metadata()`, mirroring the REST serializer:

```python
from posthog.event_usage import report_user_action

def create_action(...):
    ...
    with _acting_user(user):
        action.save()
    report_user_action(user, "action created", action.get_analytics_metadata(), team=team)
    return f"Created action:\n{_format_action(action, detailed=True)}"

def update_action(...):
    ...
    with _acting_user(user):
        action.save()
    report_user_action(
        user, "action updated",
        {**action.get_analytics_metadata(), "updated_by_creator": user == action.created_by},
        team=action.team,
    )
    return f"Updated action:\n{_format_action(action, detailed=True)}"

def delete_action(user: User, action: Action) -> str:
    action.deleted = True
    with _acting_user(user):
        action.save()
    report_user_action(user, "action updated", action.get_analytics_metadata(), team=action.team)
    return f"Deleted action #{action.id} {action.name or '(unnamed)'}."
```

- **Validator:** Fully verified parity omission. REST ActionSerializer.create()/update() fire report_user_action('action created'/'action updated', ..., team=instance.team, request=...) (products/actions/backend/api/action.py:249-255, 270-279), and REST soft-delete flows through PATCH→update() (ForbidDestroyModel), firing 'action updated' with deleted:True in get_analytics_metadata(). The tool path's create_action/update_action/delete_action (core.py:192-233) never call report_user_action, and a grep confirms these events are emitted only in the serializer — no post_save signal or model hook compensates for the tool's direct action.save(). report_user_action accepts team=/organization= without a DRF request (posthog/event_usage.py:392-401), the same no-request style already used here for check_count_limit, so there was no structural blocker — it's a straightforward oversight. Consequence is concrete and systematic (not an edge case): every action created/updated/deleted through Max is invisible to the 'action created'/'action updated' product-analytics stream that the REST/UI surface populates, silently under-counting feature adoption for the entire new AI creation surface. It matches no drop bucket (deterministic on every write, not overengineering, not already-handled, not wrong) and directly undermines a parity goal the PR explicitly pursued — the author replicated bytecode compilation, activity logging, and the check_count_limit telemetry (called out in the PR description) but missed the sibling report_user_action right beside it. Impact is observability/analytics completeness rather than user-facing correctness, hence best_practice; should_fix is appropriate given it is systematic and trivially fixable. Keeping.
