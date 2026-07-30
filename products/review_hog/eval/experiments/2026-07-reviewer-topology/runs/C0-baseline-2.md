# Reviewer-quality run — `C0-baseline-2`

- **Dumped:** 2026-07-01T20:59:17+00:00
- **Report id:** `019f1f6d-1ff1-775a-ac5f-91090d6726e6` · **PR:** https://github.com/PostHog/posthog/pull/62096
- **Head:** `ba725a897db35053525e5bdfac2c64a8b007fcb4` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 878s (14.6 min)

## Config snapshot

- runtime / model / effort: `claude` / `claude-opus-4-8` / `xhigh`
- `EXPERIMENT_FORCE_CHUNKING` = False
- effective chunk target / soft-max additions = 1000 / 1500
- `EXPERIMENT_SEQUENTIAL_PERSPECTIVES` = False
- `EXPERIMENT_COMPLETENESS_PASS` = False

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 1      | 3            | 7          | 6           | 4                |

- **review units** = every (perspective|gap × chunk) sandbox review that ran = the model-held-constant cost proxy.
- **local `$ai_generation` tokens (best-effort, may be pre-ingestion / partial):**

  | model             | gens   | input tok    | output tok |
  | ----------------- | ------ | ------------ | ---------- |
  | claude-opus-4-8   | 75     | 9992034      | 66606      |
  | claude-sonnet-4-6 | 8      | 254556       | 3427       |
  | **total**         | **83** | **10246590** | **70033**  |

## Chunking

- **chunk 1** (9 files): ee/hogai/chat_agent/toolkit.py, ee/hogai/tools/**init**.py, ee/hogai/tools/actions/**init**.py, ee/hogai/tools/actions/core.py, ee/hogai/tools/actions/tool.py, frontend/src/queries/schema.json, frontend/src/queries/schema/schema-assistant-messages.ts, frontend/src/scenes/max/max-constants.tsx, posthog/schema_enums.py

## Per-review-unit breakdown

| pass | chunk | perspective                                    | raw issues |
| ---- | ----- | ---------------------------------------------- | ---------- |
| 1    | 1     | review-hog-perspective-contracts-security      | 2          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 3          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] should_fix · best_practice — ee/hogai/tools/actions/core.py:181-189

**Action name length not validated in tool path — diverges from REST and fails ungracefully**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `_check_name_available` validates only blank and uniqueness; `create_action`/`update_action` then call `action.save()` directly. `Action.name` is `CharField(max_length=400)` (products/actions/backend/models/action.py:43), but Django does not enforce `max_length` on `.save()` — only `full_clean()` (used implicitly by the REST serializer) or the Postgres `varchar(400)` column constraint does. The REST path (`ActionSerializer`) rejects an over-length name with a clean 400 validation error. The tool path has no length check, so a name longer than 400 characters reaches Postgres and raises a `DataError`, which is not an `ActionToolError` and therefore is not caught by the `except ActionToolError` handlers in `tool.py` (lines 101-104 / 125-128). The exception propagates out of the tool as an unhandled, non-retryable error instead of a fixable message back to the LLM. This is both a contract inconsistency with the REST endpoint and a missing input-boundary check.
- **Suggestion:** Enforce the same length bound the model/serializer imposes so the tool fails with a retryable `ActionToolError` rather than a raw `DataError`. In `_check_name_available`, after the blank check add e.g. `if len(name) > 400: raise ActionToolError("Action name must be 400 characters or fewer.")` (reuse the model field's `max_length` rather than hardcoding, e.g. `Action._meta.get_field("name").max_length`). This keeps the tool contract aligned with the REST create/update path.
- **Validator:** The technical premise is correct: Django does not enforce CharField max*length on .save() (only full_clean or the Postgres varchar(400) constraint does), so a >400-char name would raise a DataError that isn't an ActionToolError and would escape the `except ActionToolError` handlers in tool.py as a non-retryable error, diverging from the REST serializer's clean 400. However, the trigger is practically unreachable — it requires an LLM to produce an action \_name* (a short human-readable label) exceeding 400 characters (~60-80 words). The description field is an unbounded TextField, so only name is at risk. Even if it fired, the impact is a single ungraceful tool error rather than a retryable one: no data loss, corruption, or security exposure. This is a defensive input-boundary check for an input that won't realistically occur, plus a minor REST-parity nicety — below the bar for surfacing under precision-over-recall.

### [✅ VALID] should_fix · bug — ee/hogai/tools/actions/core.py:34-41

**Element-matching step fields are silently dropped unless event is $autocapture**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The `selector`, `tag_name`, `text`/`text_matching`, and `href`/`href_matching` fields of `ActionStepInput` only take effect during bytecode compilation when the step's `event` is exactly `$autocapture` — see `steps_to_expr` in posthog/hogql/property.py:1230 (`if step.event == AUTOCAPTURE_EVENT:` wraps all element matching). If Max sets one of these fields with `event=None` or a non-autocapture event, the element condition is silently discarded: the step yields an empty expression list and compiles to `ast.Constant(value=True)` (property.py:1330-1331), i.e. it matches EVERY event, and `refresh_bytecode` sets no `bytecode_error`. Nothing in the tool descriptions or field descriptions communicates this coupling, so the LLM can create/update an action it believes matches 'clicks on button.cta' that in fact matches all events — a silently-incorrect result the agent cannot detect from the tool output.
- **Suggestion:** Make the constraint explicit so the tool produces correct actions: document in the `selector`/`tag_name`/`text`/`href` field descriptions (and in CREATE_ACTION_DESCRIPTION/UPDATE_ACTION_DESCRIPTION in tool.py) that these fields only apply when `event == "$autocapture"`, and/or validate it in `to_step_dict`/`create_action`/`update_action` — raise an `ActionToolError` when an element-matching field is set on a non-autocapture step so the model gets a retryable, actionable error instead of a silently over-broad action.
- **Validator:** Verified against posthog/hogql/property.py:1220-1336: element-matching step fields (selector, tag_name, href/href_matching, text/text_matching) are only compiled into the query when step.event == AUTOCAPTURE_EVENT. If an element field is set with event=None or a non-autocapture event and no url/properties are present, exprs is empty and the step compiles to ast.Constant(value=True) — matching every event — and refresh_bytecode records no bytecode_error. The tool's field descriptions (core.py L34-41) present selector/tag_name/text/href as generic element matchers with no mention of the $autocapture requirement, and the event field lists $autocapture only as an example. An LLM building 'clicks on button.cta' would naturally set selector without forcing event=$autocapture, producing a silently incorrect, over-broad action that neither the model nor the user can detect from tool output. This is a real correctness bug with a realistic trigger and concrete bad consequence, directly related to the new tool code, and the suggested fix (document the coupling in field/tool descriptions and/or raise a retryable ActionToolError on mismatched steps) is actionable.

### [✅ VALID] must_fix · security — ee/hogai/tools/actions/core.py:142-166

**list_actions bypasses object-level access control, exposing restricted actions**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `list_actions` returns every non-deleted action in the team (`Action.objects.filter(team=team, deleted=False)`) gated only by the tool's resource-level check `get_required_resource_access() -> [("action", "viewer")]`. It never applies object-level access filtering. The REST equivalent (`ActionViewSet`, via `TeamAndOrgViewSetMixin._filter_queryset_by_access_level` in posthog/api/routing.py:362-388) prunes objects the user is denied at the object level, and the established Max/hogai pattern does the same — `ee/hogai/context/entity_search/context.py:347,374,409` explicitly calls `self.user_access_control.filter_queryset_by_access_level(queryset)` after the resource-level gate (see the comment at context.py:404-405 spelling out that the resource check and object-level pruning are separate concerns). Because `list_actions` skips this, a user who has resource-level `viewer`/`editor` on actions but is explicitly restricted (a per-object `AccessControl` row with `access_level="none"`) on specific actions will still see those actions' name, description, steps, and bytecode errors in the tool output. This is the read/enumeration counterpart to the write-path object-level bypass already fixed on get/update/delete (which now call `check_object_access`), but `list_actions` returns many objects and has no per-object filtering. Note the core function signature (`team`, `search`, `limit`, `offset`) has no access-control context, so it structurally cannot filter — the fix has to thread it through.
- **Suggestion:** Apply object-level filtering to the list queryset, matching REST and the entity-search pattern. Pass the tool's access control into the core function, e.g. change `list_actions` to accept a `UserAccessControl` (or apply the filter in `ListActionsTool._arun_impl`) and filter before counting/paginating: `qs = user_access_control.filter_queryset_by_access_level(Action.objects.filter(team=team, deleted=False))`. In `ListActionsTool`, `self.user_access_control` is already available. Add a test asserting an object-level-denied action does not appear in `list_actions` output (the current suite covers cross-team isolation but not object-level ACLs).
- **Validator:** Confirmed real object-level access-control gap. list_actions (core.py:143) queries Action.objects.filter(team=team, deleted=False) with no per-object filtering, and ListActionsTool.\_arun_impl adds none. Every other equivalent path enforces object-level pruning: the REST ActionViewSet list flows through TeamAndOrgViewSetMixin.\_filter_queryset_by_access_level -> user_access_control.filter_queryset_by_access_level (routing.py:362-388), and the Max entity-search path for actions applies the same filter via search_entities_fts. The codebase explicitly documents that the resource-level gate (get_required_resource_access -> ('action','viewer')) and object-level pruning are separate concerns, so the resource check alone is insufficient. The write-path tools in this same PR already call check_object_access (tool.py:86,124,145), making list the lone unguarded read path. Consequence: a user with resource-level viewer but an object-level AccessControl row of access_level='none' on specific actions still sees their name/description/steps/bytecode errors in tool output — an enumeration/confidentiality leak. The fix is feasible since self.user_access_control is available on MaxTool (tool.py:127-134). This meets the security/permission-gap keep bar with a concrete trigger and impact; must_fix is warranted.

### [✅ VALID] consider · bug — ee/hogai/tools/actions/core.py:147-150

**list_actions pagination ordering is non-deterministic for equal/null names**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** list_actions orders by `name` only (`qs.order_by("name")`) before slicing for pagination. The `Action.name` column is nullable (`CharField(null=True, blank=True)`) and has no uniqueness constraint at the DB level (no `unique_together`/`UniqueConstraint` in the model Meta) — the app only prevents duplicate names among non-deleted actions at create/update time, so pre-existing null/blank/duplicate names can coexist. When multiple rows share the same sort key, their relative order is not guaranteed to be stable across separate queries, so paging with `offset`/`limit` across multiple tool calls can skip or duplicate actions. The REST list uses a two-key ordering (`["-last_calculated_at", "name"]`), which is more stable.
- **Suggestion:** Add a deterministic tiebreaker to guarantee stable paging, e.g. `qs.order_by("name", "id")`.
- **Validator:** Premise verified: Action.name is CharField(null=True, blank=True) with no UniqueConstraint/unique_together in the model Meta, so order_by('name') has no total ordering for tied keys, and offset/limit pagination across separate tool calls can skip or duplicate rows — a genuine, well-known pagination correctness issue. Ties are reachable because null/blank-named or otherwise duplicate actions can pre-exist (the tool only enforces unique non-blank names on its own non-deleted writes), and the REST list uses a two-key ordering while this path does not. The standard fix (order_by('name', 'id')) is a trivial, correct hardening. However, impact is low: it requires multiple rows sharing a sort key plus the LLM paging exactly across that boundary in separate calls, and the worst outcome is a rare missed/doubled action in a listing — no data loss, security, or write correctness impact. This is a real-but-minor reliability defect, which matches the reviewer's 'consider' priority: kept on record but not surfaced. Valid at consider rather than dismissed, since the technical premise holds.

### [✅ VALID] should_fix (validator→consider) · bug — ee/hogai/tools/actions/core.py:142-155,56-60

**list_actions crashes ungracefully on negative/out-of-range limit or offset**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** `limit` and `offset` come straight from the LLM and are typed `Optional[int]` with no numeric bounds (lines 56-60); the description claims a 1-100 range but nothing enforces it. In `list_actions`, `capped_limit = min(limit or DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT)` and `start = offset or 0` do not floor negatives, so a negative `limit` (e.g. -1 → `qs[0:-1]`) or negative `offset` (e.g. -1 → `qs[-1:24]`) reaches Django slicing, which raises `ValueError: Negative indexing is not supported.` Unlike every other action tool, `ListActionsTool._arun_impl` (tool.py lines 69-73) wraps nothing in try/except and raises no `MaxToolRetryableError`, so this bubbles to the base-class generic `except Exception` safety net (executables.py:563) which returns the non-recoverable message "The tool raised an internal error. Do not immediately retry...". A foreseeable, trivially-fixable bad input (the LLM picking a wrong page size/offset) is thus turned into a dead-end instead of a retryable error, defeating the retry design the sibling tools rely on. Separately, `limit=0` is silently coerced to 25 by the `or` fallback.
- **Suggestion:** Bound the inputs so bad values degrade gracefully and recoverably. Cleanest: add pydantic constraints to `ListActionsToolArgs` — `limit: Optional[int] = Field(default=None, ge=1, le=MAX_LIST_LIMIT, ...)` and `offset: Optional[int] = Field(default=None, ge=0, ...)` (a pydantic ValidationError is caught by the base class and surfaced as an informative validation message). Alternatively/additionally clamp inside `list_actions`, e.g. `start = max(offset or 0, 0)` and `capped_limit = min(max(limit or DEFAULT_LIST_LIMIT, 1), MAX_LIST_LIMIT)`, so the slice can never go negative.
- **Validator:** Mechanics confirmed: list_actions applies no floor to limit/offset (capped_limit=min(limit or 25,100), start=offset or 0), so limit=-1 -> qs[0:-1] and offset=-1 -> qs[-1:24] both hit Django slicing, which raises ValueError: Negative indexing is not supported. ListActionsTool.\_arun_impl (tool.py:69-73) has no try/except (unlike create/update), so the error bubbles to the base-class generic handler and returns the non-retryable 'internal error, do not immediately retry' message, contradicting the retryable-error design the sibling tools implement. The inputs are Optional[int] with no numeric bounds, so nothing rules the bad values out — this is not a case already handled upstream. However, the trigger requires the LLM to pass a value outside the field's explicitly documented 1-100 / non-negative range, which is uncommon, and the consequence is a single failed read call surfaced as a dead-end message — no data loss, security, or write-correctness impact. It is a genuine but minor robustness gap; the pydantic Field(ge=1, le=100)/(ge=0) fix is trivial and idiomatic. Real enough to keep on record but low-impact and rarely triggered, so lowering from should_fix to consider (soft-suppress) rather than surfacing or dismissing.

### [❌ dismissed] consider · performance — ee/hogai/tools/actions/core.py:142-150

**list_actions loads the unused bytecode JSONField for every listed action**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** `list_actions` executes `list(qs[start : start + capped_limit])`, fetching full `Action` rows for up to `MAX_LIST_LIMIT` (100) actions. However `_format_action` in the non-detailed path only reads `id`, `name`, `description`, `steps` (from `steps_json`) and `bytecode_error`. The `bytecode` JSONField (the compiled HogQL bytecode for the action, model line 54) is loaded and JSON-deserialized for every row but never used. This tool is explicitly designed for projects with "thousands of actions" and encourages repeated paginated calls, so each list/search call needlessly pulls and decodes up to 100 compiled-bytecode blobs.
- **Suggestion:** Restrict the columns fetched for the list path, e.g. `qs.only("id", "name", "description", "steps_json", "bytecode_error")` or at minimum `qs.defer("bytecode")`. `_format_action` touches none of the deferred/omitted fields, so this avoids transferring and deserializing the unused bytecode column while keeping behavior identical.
- **Validator:** The premise is factually correct: \_format_action's non-detailed path reads id, name, description, steps (steps_json), and bytecode_error but never bytecode, so list(qs[...]) hydrates the unused bytecode JSONField for up to 100 rows, and defer('bytecode')/only(...) would be behavior-identical. However, it fails the performance bar of biting at real scale. This is a single query bounded to MAX_LIST_LIMIT=100 rows fetching one extra column — no N+1, no unbounded memory, no missing index, no quadratic behavior. An action's compiled bytecode is a modest expression blob (hundreds of bytes to low KBs), so the wasted transfer/deserialization is small and negligible relative to the LLM round-trip this tool call lives inside. There is no demonstrated meaningful impact; this is a speculative micro-optimization / premature column-pruning suggestion, which the criteria classify as noise to drop rather than a real problem worth surfacing or even keeping on record.
