# Reviewer-quality run — `B-sonnet5-xhigh-1`

- **Dumped:** 2026-07-03T11:20:22+00:00
- **Report id:** `019f27a1-b6b2-7801-b7eb-8503d27ddab2` · **PR:** https://github.com/PostHog/posthog/pull/62096
- **Head:** `ba725a897db35053525e5bdfac2c64a8b007fcb4` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 1253s (20.9 min)

## Config snapshot

- runtime / model / effort: `claude` / `claude-sonnet-5` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 3      | 12           | 17         | 11          | 6                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.
- **local `$ai_generation` tokens (best-effort, may be pre-ingestion / partial):**

  | model           | gens    | input tok    | output tok |
  | --------------- | ------- | ------------ | ---------- |
  | claude-sonnet-5 | 337     | 34489917     | 239766     |
  | claude-opus-4-8 | 44      | 2904343      | 37463      |
  | **total**       | **381** | **37394260** | **277229** |

## Chunking

- **chunk 1** (1 files): ee/hogai/tools/actions/core.py
- **chunk 2** (4 files): ee/hogai/tools/actions/tool.py, ee/hogai/tools/actions/**init**.py, ee/hogai/tools/**init**.py, ee/hogai/chat_agent/toolkit.py
- **chunk 3** (4 files): frontend/src/scenes/max/max-constants.tsx, frontend/src/queries/schema/schema-assistant-messages.ts, frontend/src/queries/schema.json, posthog/schema_enums.py

## Per-review-unit breakdown

| pass | chunk | perspective                                    | raw issues |
| ---- | ----- | ---------------------------------------------- | ---------- |
| 1    | 1     | review-hog-perspective-contracts-security      | 2          |
| 1    | 2     | review-hog-perspective-contracts-security      | 2          |
| 1    | 3     | review-hog-perspective-contracts-security      | 1          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 1          |
| 3    | 1     | review-hog-perspective-performance-reliability | 3          |
| 3    | 2     | review-hog-perspective-performance-reliability | 1          |
| 3    | 3     | ?                                              | 0          |
| 1000 | 1     | review-hog-blind-spots-general                 | 2          |
| 1000 | 2     | review-hog-blind-spots-general                 | 2          |
| 1000 | 3     | review-hog-blind-spots-general                 | 1          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] should_fix · best_practice — ee/hogai/tools/actions/core.py:68-68,78-78,192-205,208-226

**`name` input has no `max_length`, so an oversized value crashes with an unhandled DB error instead of a validation error**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `Action.name` is `models.CharField(max_length=400)` (`products/actions/backend/models/action.py:43`). The REST `ActionSerializer` is a `ModelSerializer`, so DRF auto-derives a `max_length=400` validator for `name` from the model field, rejecting an over-long name with a clean validation error before it ever reaches the database. `CreateActionToolArgs.name` (line 68) and `UpdateActionToolArgs.name` (line 78) are plain `str` fields with no length constraint, and `create_action`/`update_action` (lines 192-226) call `action.save()` directly — `Action.save()` only calls `refresh_bytecode()`, it never calls `full_clean()` or otherwise validates field lengths. An LLM-supplied name longer than 400 characters is therefore written straight through to Postgres, which raises `DataError: value too long for type character varying(400)` — an unhandled exception surfaced to the agent instead of the intended retryable `ActionToolError` path that duplicate-name/blank-name violations already get via `_check_name_available`.
- **Suggestion:** Constrain `name` to match the model field, e.g.:

```python
name: str = Field(max_length=400, description="Name of the action (must be unique within the project).")
```

in both `CreateActionToolArgs` and `UpdateActionToolArgs`, so an oversized name fails Pydantic validation up front (same effective behavior as the REST serializer's derived `max_length` validator) rather than raising a raw DB error.

- **Validator:** The premise is technically correct: Action.name is varchar(400), Action.save() never calls full_clean(), the two Pydantic arg models omit a length constraint, and the tool wrappers only catch ActionToolError — so a >400-char name would indeed raise an unhandled DataError instead of a retryable ActionToolError. However, this is a practically unreachable edge case with negligible impact. The trigger requires an LLM to generate an action name exceeding 400 characters; action names are inherently short, making this input essentially never occur in practice. When it does, the only consequence is a less-graceful error surface (raw exception vs. clean retryable error) — no data loss, corruption, security hole, or contract break. Per the precision-over-recall bar, a real-but-negligible robustness gap on an input that won't realistically happen should be dropped rather than surfaced as a should_fix. The existing blank-name and duplicate-name checks cover the input-validation cases that genuinely occur.

### [❌ dismissed] must_fix · security — ee/hogai/tools/actions/tool.py:61-73

**ListActionsTool leaks actions restricted by object-level access control**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** ListActionsTool.\_arun_impl only enforces the resource-level check declared by get_required_resource_access() ([("action", "viewer")]) and then calls list_actions(self.\_team, search, limit, offset), whose queryset in ee/hogai/tools/actions/core.py (Action.objects.filter(team=team, deleted=False) plus an optional name\_\_icontains filter) applies no object-level access-control filtering at all. This is the same class of bug already found and fixed in this PR for UpdateActionTool/DeleteActionTool (object-level bypass, fixed in 4ec2d248) and for GetActionTool (which now calls `await self.check_object_access(action, "viewer", action="read")` before returning data) — but it was missed for the list path. Every comparable listing surface for the same Action model does filter by object-level access: the REST ActionViewSet list endpoint filters via TeamAndOrgViewSetMixin.get_queryset() -> self.\_filter_queryset_by_access_level() -> user_access_control.filter_queryset_by_access_level(), and PostHog's own entity-search/taxonomy code (posthog/api/search.py:class_queryset, used by Max's own entity_search tool for the "action" entity type) calls `view.user_access_control.filter_queryset_by_access_level(qs)` right after the team filter. Because list_actions skips this, a user with resource-level "viewer" but an explicit per-object "none"/restricted AccessControl row on a specific action can still see that action's name, description, and full step/trigger definitions (CSS selectors, URLs, property filters) through Max, even though the REST API, the UI actions list, and Max's own taxonomy search would all hide it from them.
- **Suggestion:** Filter the list_actions queryset by object-level access before slicing/counting, mirroring posthog/api/search.py's class_queryset pattern: `qs = self.user_access_control.filter_queryset_by_access_level(qs)` (MaxTool already exposes `self.user_access_control`, used elsewhere in tool.py for check_object_access/\_check_resource_access). Since list_actions lives in core.py and is a plain function today, either pass the already-filtered queryset in from the tool (fetch qs = Action.objects.filter(team=team, deleted=False) filtered via `tool.user_access_control.filter_queryset_by_access_level(qs)` before calling list_actions), or thread the UserAccessControl instance into list_actions so the count/total and pagination reflect only actions the caller may view.
- **Validator:** The issue's core premise is unreproducible for the action resource. `minimum_access_level("action")` returns `"viewer"` (posthog/rbac/user_access_control.py:169-170), and this floor is enforced at write time in `AccessControlSerializer.validate_access_level` (ee/api/rbac/access_control.py:107-112), which rejects any AccessControl row — member- or role-scoped, object-level included — set below `"viewer"`. So the described scenario (a per-object `"none"`/restricted AccessControl on a specific action) is impossible: no action can ever be below `"viewer"`, and the resource default is `"editor"`. Consequently every user who passes the resource-level `("action", "viewer")` gate can legitimately read every action in the project, and `filter_queryset_by_access_level` (in search.py and the REST viewset) would never exclude any action for such a user. `list_actions` omitting that filter therefore leaks nothing. The asymmetry the reviewer flagged is correct by design: update/delete require `"editor"`, where a per-object `"viewer"` restriction is meaningful, so those object-level checks are real and necessary; list/get require only `"viewer"`, the floor, which is always satisfied. `GetActionTool`'s `check_object_access(action, "viewer")` is itself effectively a no-op, so mirroring it onto the list path would add cost without any access-control benefit. This falls under 'wrong/unreproducible' and 'already handled elsewhere' (the minimum-access floor).

### [✅ VALID] should_fix · bug — ee/hogai/tools/actions/core.py:56-60,142-150

**Negative or zero `limit`/`offset` in list_actions crash with an unhandled ValueError instead of a retryable error**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `ListActionsToolArgs.limit`/`offset` are declared as plain `Optional[int]` with no lower-bound validation, and `list_actions` combines them with Python truthiness rather than an explicit `None` check: `capped_limit = min(limit or DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT)` and `start = offset or 0`. Two concrete bugs follow: (1) an explicit `limit=0` is silently treated as 'not provided' and replaced with `DEFAULT_LIST_LIMIT` (25) because `0` is falsy, contradicting the documented range 'Maximum number of actions to return (1-100, default 25)'; (2) any negative `limit` or `offset` (e.g. `limit=-1`, `offset=-5`) flows straight into `qs[start : start + capped_limit]`. Django's `QuerySet.__getitem__` explicitly rejects negative slice bounds and raises `ValueError('Negative indexing is not supported.')` before any SQL is issued. That raw `ValueError` is not an `ActionToolError`, so it bypasses this module's own retryable-error convention (used everywhere else in the file for user-fixable input problems) and instead propagates as an unrecoverable, fatal `MaxToolError` per `ee/hogai/tool_errors.py`'s 'Generic Exception: Unknown failures, treated as fatal' fallback — turning what should be a simple, correctable input mistake into a dead-end for the agent.

This is a real regression from the established pattern in this exact tool family: every other paginated Max tool in `ee/hogai/tools/` bounds these fields at the pydantic layer, e.g. `ee/hogai/tools/list_data.py:55-56` (`limit: int = Field(default=100, ge=1, le=100, ...)`, `offset: int = Field(default=0, ge=0, ...)`), `ee/hogai/tools/list_feature_flags.py:39-40`, `ee/hogai/tools/read_data/tool.py:196-197`, and `ee/hogai/tools/read_taxonomy/core.py:15-16` all use the identical `ge=`/`le=` constraint pattern specifically to prevent this class of bug. `ListActionsToolArgs` is the outlier that omits it.

- **Suggestion:** Match the sibling tools' convention: give `limit`/`offset` non-optional defaults with explicit bounds, e.g.

```python
class ListActionsToolArgs(BaseModel):
    search: Optional[str] = Field(default=None, description=...)
    limit: int = Field(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT, description=...)
    offset: int = Field(default=0, ge=0, description=...)
```

and simplify `list_actions` to use the values directly (`capped_limit = min(limit, MAX_LIST_LIMIT)`, `start = offset`) instead of `or`-based coalescing. This makes pydantic reject out-of-range values before they ever reach the queryset slice, eliminating both the silent `limit=0` fallback and the unhandled `ValueError` crash on negative input, and brings this tool in line with the other Max tools in the same directory.

- **Validator:** Verified against the codebase. list_actions (core.py:142-150) uses `capped_limit = min(limit or DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT)` and `start = offset or 0`, and ListActionsToolArgs declares limit/offset as plain Optional[int] with no bounds. Both claimed bugs are real: (1) limit=0 is falsy so it's silently replaced with 25, contradicting the field's documented 1-100 range; (2) a negative offset/limit flows into `qs[start:start+capped_limit]`, and Django's QuerySet.**getitem** raises ValueError('Negative indexing is not supported.') before any SQL. That ValueError is not an ActionToolError, so the tool wrappers don't convert it to MaxToolRetryableError — I confirmed via tool_errors.py that generic exceptions are treated as fatal ('Unknown failures, treated as fatal'), turning a correctable input mistake into a dead-end for the agent, which is exactly what the module's retryable-error convention exists to avoid. The reachability is materially higher than a hypothetical: pagination is where LLMs do arithmetic (e.g. offset - limit going negative when paging backward), and a confused model passing limit=0/negative is plausible. This is also a clear deviation from an established convention — list_data.py, list_feature_flags.py, read_data/tool.py, and read_taxonomy/core.py all bound limit/offset with ge=/le= at the pydantic layer; ListActionsToolArgs is the sole outlier. The fix is trivial and matches the sibling pattern. Concrete trigger and concrete consequence are both nameable, meeting the keep bar.

### [❌ dismissed] should_fix · documentation — frontend/src/scenes/max/max-constants.tsx:151-161,176-227

**New action tools missing from DEFAULT_TOOL_KEYS, so Auto-mode tooltip understates actual capabilities**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `ee/hogai/chat_agent/toolkit.py`'s `DEFAULT_TOOLS` list (backend) was updated in this PR to include `ListActionsTool`, `GetActionTool`, `CreateActionTool`, `UpdateActionTool`, and `DeleteActionTool` — these are explicitly commented as 'used across all agent modes'. However, the frontend `DEFAULT_TOOL_KEYS` array in `max-constants.tsx` (lines 151-161), which feeds `getDefaultTools()`, was not updated to include the five new keys (`list_actions`, `get_action`, `create_action`, `update_action`, `delete_action`) even though the corresponding `TOOL_DEFINITIONS` entries were added at lines 176-227. `getDefaultTools()` is consumed by `ModeSelector.tsx` to build the 'Tools:' tooltip shown for the Auto mode option and the general mode-selector dropdown (which explicitly states 'Each mode unlocks specialized capabilities, tools, and expertise'). As a result, after this PR, Max can actually call the new action CRUD tools in every mode, but the UI that is supposed to advertise available tools to the user will not list them — directly undermining the PR's stated goal of making actions discoverable/usable in Max. This is a data-mapping inconsistency between the backend tool-registration source of truth and the frontend's display-list mirror of it, introduced by only completing half of the required wiring (definitions added, default-key list not updated).
- **Suggestion:** Add the five new keys to `DEFAULT_TOOL_KEYS` in max-constants.tsx so the Auto-mode tooltip reflects reality, e.g.:

```ts
export const DEFAULT_TOOL_KEYS: (keyof typeof TOOL_DEFINITIONS)[] = [
  'read_taxonomy',
  'read_data',
  'list_data',
  'list_feature_flags',
  'list_actions',
  'get_action',
  'create_action',
  'update_action',
  'delete_action',
  'search',
  'switch_mode',
  'list_llm_skills',
  'get_llm_skill',
  'get_llm_skill_file',
]
```

If the omission is intentional (e.g. deliberately keeping the tooltip curated/short like the existing omissions of `todo_write`/`create_form`/`create_notebook`), that should be a conscious call, not an oversight — worth confirming with the author since these are exactly the kind of user-facing capability (per the PR's own stated purpose) that this tooltip is meant to surface.

- **Validator:** The premise is partly mistaken. The frontend DEFAULT_TOOL_KEYS is not a strict mirror of the backend DEFAULT_TOOLS — it is already a deliberately curated subset that omits todo_write, create_form, and create_notebook, all write/mutation tools that ARE in the backend default set. So omitting the action write tools (create/update/delete_action) is consistent with the existing curation pattern, not a half-completed wiring bug. Functionally, getDefaultTools() only builds a display string for the Auto/Plan mode tooltips in ModeSelector.tsx; it has no bearing on which tools Max can actually invoke (that is driven entirely by the backend toolkit). So there is no correctness, contract, security, or reliability impact — the flag is a purely cosmetic tooltip-completeness observation. At most, the read-only list_actions/get_action could be argued to fit alongside the included read tools, but that is a product/design curation judgment, not a defect, and the reviewer's own suggested fix (adding all five, including the write tools) would actually contradict the established curation pattern. Under precision-over-recall this does not meet the bar for surfacing.

### [❌ dismissed] should_fix · best_practice — ee/hogai/tools/actions/core.py:181-189,192-205,208-226

**TOCTOU race on action name uniqueness lets concurrent tool calls silently create duplicates**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** `_check_name_available` (lines 181-189) does a plain SELECT, and `create_action`/`update_action` later call `action.save()` with no transaction or row lock in between. The underlying `Action` model has no DB-level unique constraint on `(team, name)` (only an index on `team_id`/`-updated_at`) — uniqueness is enforced purely at the application layer. Two overlapping tool invocations for the same team (plausible for an AI agent: e.g. a retry fired while a previous call is still in flight, or two concurrent conversations) can both pass the availability check before either commits, resulting in two actions with the same name and no error surfaced anywhere — the tool's own contract (`CreateActionToolArgs.name`: "must be unique within the project") is silently violated rather than rejected.
- **Suggestion:** Serialize the check-and-write with `transaction.atomic()` plus a locking read (e.g. `select_for_update()` on the team row, or on the matching `Action` rows for `update_action`) so a concurrent writer blocks until the first transaction commits and can then see the newly created row when it re-checks. If a full lock is too heavy, consider a `try`/`except IntegrityError` fallback after adding a `UniqueConstraint(fields=['team', 'name'], condition=Q(deleted=False))` at the DB layer — that would also protect the pre-existing REST create path.
- **Validator:** The premise is technically accurate — \_check_name_available does a plain SELECT, save() follows with no transaction or row lock, and the Action model has no DB-level unique constraint on (team, name) (confirmed: Meta only declares an index on team_id/-updated_at). So a TOCTOU window genuinely exists. But this fails the worth-surfacing bar on several fronts. First, reachability is low: an AI agent's tool calls within a conversation are sequential, and the scenario requires two same-team create/update calls for the identical name to overlap within a sub-transaction window — a rare event. Second, the impact is minor: the outcome is two actions sharing a name, which the data model explicitly tolerates (no unique constraint by design), and which is already possible via the existing REST create path that uses the same non-atomic app-level check — so this is not a regression introduced by the PR but a pre-existing, accepted app behavior. Third, the suggested fix is disproportionate to the tool PR: adding a DB UniqueConstraint via migration would change product-wide behavior and could fail against existing duplicate rows, and select_for_update adds locking complexity for a race that produces a low-impact, non-corrupting result. This is the kind of speculative concurrency 'what if' with low probability and low impact that the criteria direct dropping, especially given precision-over-recall.

### [❌ dismissed] should_fix · best_practice — ee/hogai/tools/actions/core.py:203-205,224-226

**Unprotected save() side effects can leave create/update in an ambiguous partial-success state, inviting a duplicate-creating retry**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** `action.save()` in `create_action`/`update_action` triggers `Action.save()`, which unconditionally fires a `post_save` signal that publishes a Redis message to reload the action on plugin-server workers (`reload_action_on_workers` → `publish_message`, which has no try/except around the Redis call). If the DB write succeeds but that Redis publish then raises (e.g. a brief Redis blip), the exception propagates straight out of `action.save()` uncaught — nothing in `core.py` wraps the call. The generic agent-level exception handler (`AgentToolsExecutable.arun`) catches it and returns a vague "the tool raised an internal error" message with no indication that the underlying `Action` row was actually committed. An agent seeing this generic failure has a strong incentive to retry `create_action` with the same name, which — combined with the missing DB-level uniqueness guard (see companion finding) — can silently produce a duplicate action instead of surfacing a clear, actionable error.
- **Suggestion:** Wrap `action.save()` in `create_action`/`update_action` with a narrow try/except that distinguishes DB-commit failures from post-save side-effect failures (or at minimum logs/annotates that the row may already exist), and raise an `ActionToolError` with a message like "Action #<id> may have already been created; check with list_actions before retrying" rather than letting an opaque exception fall through to the generic internal-error path.
- **Validator:** This is a stacked, speculative 'what if' that fails the worth-surfacing bar. It requires a compound chain of low-probability conditions to all line up: (1) the DB write commits successfully, (2) the post_save Redis publish then fails in the narrow window afterward (a transient Redis blip), (3) the agent decides to retry create with the identical name, and (4) the companion no-unique-constraint race — which I already assessed as not worth surfacing — allows the retry to produce a duplicate. Each link is individually rare and the finding only 'bites' when all four coincide. The end impact is a duplicate-named action, which the Action model tolerates by design (no unique constraint) and is already possible on the existing REST path, since Action.save() fires the same post_save/reload_action_on_workers signal there too — this is not a regression introduced by the PR. The suggested fix (a try/except that distinguishes DB-commit failures from post-save side-effect failures and annotates possible partial success) is exactly the kind of defensive-coding elaboration against a practically-unreachable scenario that the criteria direct dropping. Precision over recall applies squarely here.

### [✅ VALID] consider · best_practice — ee/hogai/tools/actions/core.py:142-166

**Offset pagination in list_actions has no tie-breaking sort key for equal names**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** `list_actions` paginates with `qs.order_by("name")` plus `offset`/`limit` slicing, but `name` alone is not guaranteed unique (see companion race-condition finding, and even absent that, nothing prevents two actions sharing a name today). Without a secondary deterministic key (e.g. `pk`), Postgres does not guarantee a stable relative order for rows with equal `name` across separate queries, so an agent paging through results via increasing `offset` could see the same action twice or skip one entirely between calls if the table is concurrently modified.
- **Suggestion:** Add a stable tie-breaker to the ordering, e.g. `qs.order_by("name", "id")`, so repeated paginated calls return a deterministic, gap-free sequence.
- **Validator:** The premise is correct: list_actions uses qs.order_by('name') with offset/limit slicing and no secondary key, and since name is not unique (the model has no unique constraint and duplicates are possible), Postgres gives no stable relative order for equal-named rows across separate queries. Adding a deterministic tie-breaker (order_by('name', 'id')) is the standard, well-established practice for gap-free offset pagination, and the fix is trivial and unambiguously correct. The practical impact is genuinely small — it only manifests when duplicate names exist AND the table is concurrently modified mid-paging, producing a repeated or skipped row rather than any data corruption — which is why the reviewer's 'consider' priority is appropriate: this is a real-but-minor correctness nuance worth keeping on record without prominently surfacing it. It is not overengineering or a speculative abstraction; it's a concrete, low-cost determinism improvement. Keeping at the reviewer's 'consider' tier.

### [✅ VALID] should_fix (validator→consider) · performance — ee/hogai/tools/actions/core.py:13-16,105-139,160-160

**list_actions caps item count but not per-item size, undermining the tool's own "bounded output" design goal**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The module comment at lines 13-14 and the PR description both state that list_actions is safe from blowing up the agent context window because item count is capped (MAX_LIST_LIMIT=100) and per-action output is compact ("no per-action created_by payload"). That only bounds the number of rows, not the size of each row. \_format_action's non-detailed branch (line 134) still calls \_format_step (105-121) for every step of every action and joins the full rendering of each step's selector, text, href, url, and tag_name verbatim via !r into the output. None of those fields have any length limit at the pydantic input layer (ActionStepInput, lines 27-45) or on the underlying Action model/JSONField, so a single action with one step containing a long selector or long text-match value (e.g. copied from a large DOM snippet or long marketing copy) is rendered in full for every page of list_actions results, not summarized or truncated. A team with a handful of actions using verbose selectors/text can already produce an oversized response even with the default 25-item page, defeating the exact design goal the surrounding comment claims to guarantee.
- **Suggestion:** Truncate long field values in \_format_step (e.g. cap selector/text/href/url to ~80-100 chars with an ellipsis) when rendering the non-detailed list view, or drop full step rendering from list_actions entirely and only show a step count/summary there (reserving full detail for get_action via format_action_detail, which is already separate).
- **Validator:** The premise checks out: list_actions' non-detailed branch (core.py:134) renders every step of every action via_format_step, emitting selector/text/href/url/tag verbatim with !r, and neither ActionStepInput nor the Action JSONField caps those field lengths. So the count cap (MAX_LIST_LIMIT) bounds row count but not per-row size, which is a genuine gap against the module comment's stated 'bounded output' goal — and long autocapture CSS selectors or long text-match values are realistic in practice, so this isn't purely hypothetical. However, the impact is soft: the worst case is a larger-than-ideal tool response consuming context, not a crash, data loss, security issue, or contract break. It requires actions with unusually verbose step fields to become meaningful, and even then the count cap keeps it bounded to a finite (if large) size. That makes it a real-but-minor, situational quality concern rather than a should_fix. Downgrading to 'consider': the observation is legitimate and the fix (truncate step fields in the list view, or show only a step count there and reserve full detail for get_action) is cheap and sensible, but the severity does not warrant prominent surfacing.

### [✅ VALID] should_fix (validator→consider) · best_practice — ee/hogai/tools/actions/core.py:181-189,192-205,208-226

**Action name is not trimmed before the uniqueness check or save, unlike the REST path, letting whitespace-padded near-duplicates bypass the tool's own uniqueness contract**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** CreateActionToolArgs/UpdateActionToolArgs document that "name ... must be unique within the project" (line 68), but \_check_name_available (181-189) only calls name.strip() to reject a fully-blank name -- it never normalizes the value actually compared or stored. create_action (200) and update_action (219) assign the raw, untrimmed name straight onto action.name, and the uniqueness lookup at line 184 (Action.objects.filter(team_id=team_id, name=name, ...)) does an exact-string match against that same untrimmed value. This diverges from the REST path: ActionSerializer is an auto-generated ModelSerializer, so its name field is a plain DRF CharField with the library default trim_whitespace=True, meaning REST-created/updated actions always have whitespace stripped before the equivalent uniqueness check in ActionViewSet's validate() (products/actions/backend/api/action.py). An LLM that passes a name with leading/trailing whitespace (e.g. " Signup" from a copy-pasted string) via this tool will (a) have that literal padded string persisted to Action.name -- inconsistent with data created via REST/UI -- and (b) pass \_check_name_available even when an action already exists with the visually identical trimmed name "Signup", since the two strings are not equal. The result is two actions that look identical in every UI surface but are treated as distinct, silently violating the uniqueness guarantee the tool itself advertises.
- **Suggestion:** Normalize the name once at the top of \_check_name_available / before assignment (e.g. name = name.strip()) and use the trimmed value both for the availability check and for the value written to action.name in create_action/update_action, matching DRF's default trim_whitespace behavior used by the REST path.
- **Validator:** The divergence is real and confirmed. In the REST path, ActionSerializer's name field is auto-generated by ModelSerializer as a DRF CharField with the library default trim_whitespace=True, so attrs['name'] is already stripped by the time ActionViewSet.validate() (products/actions/backend/api/action.py:202-231) runs its uniqueness check and the value is stored. The tool path does not replicate this:\_check_name_available only calls name.strip() to test for blankness (core.py:182) but compares and stores the raw untrimmed value, and create_action/update_action assign name verbatim. So a name like ' Signup' would (a) persist with padding, inconsistent with REST/UI-created data, and (b) pass the exact-match uniqueness check even when 'Signup' already exists, silently creating a visually-identical near-duplicate that contradicts the tool's advertised 'must be unique within the project' contract. This is a silent wrong-result/consistency gap (worse in kind than a loud error), and the fix is a trivial one-liner matching existing app behavior. However, the trigger — an LLM emitting a leading/trailing-whitespace name argument — is uncommon since models generally produce clean strings, and the impact is low (a padded name or one near-duplicate, no data loss/corruption/security). That makes it real-but-minor rather than a should_fix. Downgrading to 'consider' to keep it on record without prominent surfacing.

### [✅ VALID] should_fix (validator→consider) · best_practice — ee/hogai/tools/actions/tool.py:98-105,116-129,151-155

**Action create/update/delete via Max tools emit no product-analytics event, unlike the REST path and this PR's own cited reference tool**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** `CreateActionTool._arun_impl`, `UpdateActionTool._arun_impl`, and `DeleteActionTool._arun_impl` all delegate to `create_action`/`update_action`/`delete_action` in `core.py`, none of which call `report_user_action`. The REST path they're meant to mirror does: `ActionSerializer.create()` fires `report_user_action(..., "action created", instance.get_analytics_metadata(), ...)` and `ActionSerializer.update()` fires `"action updated"` (the REST API also uses `update()` — not a hard DELETE — to soft-delete an action by setting `deleted=True`, so REST-originated deletes go through this same `"action updated"` event). The PR's own description points to `UpsertDashboardTool` as the pattern to follow for object-level access, and that same tool independently establishes the analytics convention for Max-originated writes: it explicitly calls `report_user_action(self._user, event, {**dashboard.get_analytics_metadata(), "source": EventSource.POSTHOG_AI, ...}, team=self._team)` after every create/update, tagging the event with `EventSource.POSTHOG_AI` so it's attributable to Max rather than the REST UI. `Action.get_analytics_metadata()` already exists and is used by the REST serializer for exactly this purpose, so the same data is available here but unused. As a result, actions created, edited, or deleted through Max leave no trace in any "action created"/"action updated" analytics stream that other internal tooling or dashboards may rely on to measure action usage — a silent telemetry gap introduced by this PR's write paths, not present in the REST path they mirror.
- **Suggestion:** In `core.py`, call `report_user_action` from `create_action`/`update_action`/`delete_action` (or from the tool layer, matching `UpsertDashboardTool`'s approach) using `action.get_analytics_metadata()` and tagging `source: EventSource.POSTHOG_AI`, e.g.:

```python
report_user_action(
    user, "action created", {**action.get_analytics_metadata(), "source": EventSource.POSTHOG_AI}, team=team
)
```

mirroring the exact call already made in `ee/hogai/tools/upsert_dashboard/tool.py`.

- **Validator:** The factual premise is verified: the REST ActionSerializer fires report_user_action for 'action created' (products/actions/backend/api/action.py:249) and 'action updated' (:270, which also covers REST soft-deletes), and the sibling UpsertDashboardTool cited by this PR deliberately fires report_user_action tagged with EventSource.POSTHOG_AI plus get_analytics_metadata() for Max-originated writes (ee/hogai/tools/upsert_dashboard/tool.py:261-282). Action.get_analytics_metadata() exists (models/action.py:103). The Max action tools' core.py functions (create_action/update_action/delete_action) call none of these, so actions created/edited/deleted through Max emit no product-analytics event, unlike both the REST path and the sibling tool. This is a real, non-speculative consistency gap with demonstrated team intent (the convention is established in the exact tool this PR points to as its pattern). However, it is not a correctness, security, data-loss, or contract defect: no user-facing behavior breaks, and the writes still flow through Action.save(), which emits the activity-log audit trail (noted in the PR description), so the writes are not untraceable — only the PostHog-internal usage-metrics event is missing, meaning Max-originated action writes would be undercounted in internal feature-adoption dashboards. That is a genuine-but-minor observability gap rather than a should-fix defect, so it is worth keeping on record but soft-suppressing.

### [✅ VALID] consider · code_quality — frontend/src/scenes/max/max-constants.tsx:176-185

**list_actions displayFormatter drops the search/pagination context that sibling list tools in the same file already surface**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The backend `ListActionsTool` (`ee/hogai/tools/actions/tool.py`) takes `search`, `limit`, and `offset` args, and the PR description specifically calls out case-insensitive name `search` as a key design feature that keeps discovery from flooding context. But the `list_actions` entry's `displayFormatter` (lines 180-184) just calls `skillStatusFormatter` with static `completedLabel`/`pendingLabel` strings ('Listed actions' / 'Listing actions') and no `nameArgKey`, so it never surfaces the search term or pagination info to the user. This is a real regression in informativeness relative to the two other list-type tools in this exact file: `list_data` (lines 557-572) builds `entityLabel`/`pageInfo` from `toolCall.args.kind`/`args.offset` to render e.g. 'Listed actions (page 2)', and `list_feature_flags` (lines 573-584) builds a `label` from `args.status` to render e.g. 'Listed enabled feature flags'. Both established precedents thread the relevant filter/pagination args into the chat message; `list_actions` silently drops them, so a user watching Max search actions by name (e.g. `search: "checkout"`) sees a generic 'Listing actions...' with no indication of what's being searched or which page, unlike the equivalent experience for data/flag listing.
- **Suggestion:** Give `list_actions` a custom `displayFormatter` (instead of the generic `skillStatusFormatter` call) that reads `toolCall.args?.search` and `toolCall.args?.offset` the same way `list_data`/`list_feature_flags` do, e.g.:

```tsx
list_actions: {
    name: 'List actions',
    description: 'List actions in the project',
    icon: <IconList />,
    displayFormatter: (toolCall) => {
        const search = typeof toolCall.args?.search === 'string' ? toolCall.args.search : null
        const offset = typeof toolCall.args?.offset === 'number' ? toolCall.args.offset : 0
        const suffix = search ? ` matching "${search}"` : ''
        const pageInfo = offset > 0 ? ` (page ${Math.floor(offset / 25) + 1})` : ''
        return toolCall.status === 'completed'
            ? `Listed actions${suffix}${pageInfo}`
            : `Listing actions${suffix}${pageInfo}...`
    },
},
```

- **Validator:** The claim checks out against the code. Both sibling list tools in the same file thread their filter/pagination args into the chat label: list_data (lines 561-571) derives entityLabel from args.kind and a pageInfo from args.offset, and list_feature_flags (lines 577-583) builds a label from args.status plus pageInfo. The new list_actions entry (lines 180-184) instead calls the generic skillStatusFormatter with static strings and no arg threading, even though the backend ListActionsTool accepts search/limit/offset and the PR explicitly frames case-insensitive search as a core discovery feature. So a user watching Max search actions by name sees a generic 'Listing actions...' with none of the context its siblings surface. This is a genuine, concrete informativeness/consistency gap backed by clear in-file precedent, not speculation or style-nitpicking — but it is purely cosmetic (display label only, no functional/correctness/data impact). That places it squarely in the real-but-minor 'consider' bucket, which is exactly the priority the reviewer assigned, so no adjustment is warranted. Minor note: the suggested snippet hardcodes a page size of 25 for its Math.floor(offset/25) math, which should match the tool's actual default/limit to stay accurate — an implementation detail for the author, not a reason to drop.
