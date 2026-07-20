# PR Review Report

**PR:** #62096 - feat(ph AI): add action CRUD tools to ph AI
**Author:** sampennington
**State:** open
**Base Branch:** master
**Head Branch:** posthog-code/max-action-tools

## Summary

This report contains detailed analysis of 3 chunks with their associated issues and validation results.

## Table of Contents

- [Chunk 1](#chunk-1)
- [Chunk 2](#chunk-2)
- [Chunk 3](#chunk-3)

## Chunk 1

### Overview

**Type:** business_logic

**Files:**

- `ee/hogai/tools/actions/__init__.py`
- `ee/hogai/tools/actions/core.py`
- `ee/hogai/tools/actions/tool.py`

**Key Changes:**

- Adds the action CRUD Max tools: list, get, create, update, and delete.
- Implements bounded listing, action formatting, retryable user-facing errors, resource limit telemetry, soft delete, activity attribution, and dangerous-operation approval for deletes.
- Enforces resource and object-level access checks in the tool layer before reading, updating, or deleting actions.

### Analysis

**Goal:** This chunk adds the core business logic and Max tool wrapper package for action CRUD in PostHog AI. It introduces ee/hogai/tools/actions as a new tool module exporting ListActionsTool, GetActionTool, CreateActionTool, UpdateActionTool, and DeleteActionTool. The synchronous core.py layer defines the Pydantic argument schemas, action step input normalization, compact formatting helpers, bounded list/search/pagination behavior, duplicate and blank name validation, create/update/delete operations, and user-facing ActionToolError failures that the async tool layer can convert into retryable Max errors.

Architecturally, the implementation follows the existing MaxTool pattern: tool.py exposes LangChain/Max-compatible tool classes, declares resource-level access through get_required_resource_access, bridges sync Django ORM work with database_sync_to_async, and performs object-level access checks via MaxTool.check_object_access before reading, updating, or deleting an individual Action. The tool layer keeps permission orchestration and dangerous-operation approval separate from the core CRUD functions, while the core layer operates directly on products.actions.backend.models.action.Action. Reads return formatted plain-text summaries for the LLM; writes call Action.save so existing bytecode compilation, post-save worker reload behavior, file-system syncing, and model activity logging continue to run through the normal model path.

The integration points are the PostHog AI tool registry, the generated AssistantTool enum values, the chat/research toolkit wiring elsewhere in the PR, the Action model and action REST semantics, resource limit telemetry, RBAC object access controls, and the dangerous-operation approval flow. Notable design decisions are using direct model operations instead of fabricating a DRF request for ActionSerializer, hard-capping list output at 100 results to protect the agent context window, converting user-correctable problems into MaxToolRetryableError, setting activity_storage around saves so activity entries are attributed to the acting user outside request middleware, and implementing delete as a soft delete gated behind explicit approval.

### Issues and Validations

#### ✅ Issue 1-1-1: Action activity attribution still uses the creator on updates and deletes

**Priority:** should_fix

**File:** `ee/hogai/tools/actions/core.py` (lines [LineRange(start=94, end=104), LineRange(start=224, end=231)])

**Issue:** The new `_acting_user()` context is intended to attribute direct ORM saves to the Max user, but the Action activity-log receiver currently ignores the `user` emitted by `ModelActivityMixin` and logs `after_update.created_by` instead. As a result, Max updates and deletes by a user who did not create the action will still be recorded as if the creator performed them, so the advertised activity attribution does not actually work for the mutating tool paths.

**Suggestion:** Update `products/actions/backend/activity_logging.py` to accept/use the signal user, e.g. `def handle_action_change(..., user, was_impersonated=False, **kwargs)` and pass `user=user or after_update.created_by` to `log_activity`. Add a Max tool test that creates an action as one user, updates/deletes it as another, and asserts the activity log actor is the acting user.

**Validation Result:** Valid

**Argumentation:** The issue is valid. ee/hogai/tools/actions/core.py wraps create/update/delete saves in _acting_user(user), and ModelActivityMixin.save emits that value as the model_activity_signal user. However products/actions/backend/activity_logging.py.handle_action_change does not accept the user parameter and instead calls log_activity(user=after_update.created_by). For updates and soft deletes of an action originally created by someone else, the activity log will attribute the change to the creator, not the Max/tool actor. That defeats the PR's stated attribution behavior and leaves an inaccurate audit trail for mutating tool paths, and likely also affects existing REST/direct-save updates where the request user differs from created_by.

**Category:** bug

---

#### ✅ Issue 1-1-2: Action names are not normalized or length-validated before direct model saves

**Priority:** should_fix

**File:** `ee/hogai/tools/actions/core.py` (lines [LineRange(start=181, end=189), LineRange(start=195, end=200), LineRange(start=217, end=219)])

**Issue:** The tool path bypasses `ActionSerializer`, but only reimplements blank and duplicate checks. It checks `name.strip()` for blankness while still storing the original untrimmed value, which lets names like `" Signup "` bypass the duplicate check for `"Signup"`. It also does not enforce the model's `max_length=400`, so an overlong LLM-generated name can reach `action.save()` and fail as an uncaught database error instead of a retryable tool error.

**Suggestion:** Centralize name validation/normalization in the core layer: trim the name once, reject blank or names longer than `Action._meta.get_field("name").max_length`, use the normalized value for the duplicate query, and assign the normalized value on create/update. Surface validation failures as `ActionToolError` so the tool can return a retryable correction prompt.

**Validation Result:** Valid

**Argumentation:** The issue is valid. `ee/hogai/tools/actions/core.py` creates and updates `Action` directly, so it does not get DRF `CharField` normalization or model-field `max_length` validation from `ActionSerializer`. `_check_name_available()` only tests `name.strip()` for blankness, then queries and saves the original value, so `" Signup "` can coexist with the normalized REST-created `"Signup"` even though the tool is intended to mirror the REST action semantics. `Action.name` is `CharField(max_length=400)`, and Django model `save()` does not run full validation, so an overlong tool-provided name can reach Postgres and fail as an uncaught database error instead of being converted into `ActionToolError`/`MaxToolRetryableError`. This should be fixed in the tool/core validation path for consistency and better retry behavior.

**Category:** bug

---

#### ✅ Issue 1-1-3: Negative list pagination arguments can break the action listing query

**Priority:** should_fix

**File:** `ee/hogai/tools/actions/core.py` (lines [LineRange(start=56, end=60), LineRange(start=148, end=150)])

**Issue:** `limit` and `offset` are described as bounded pagination inputs, but the schema does not enforce those bounds and `list_actions()` uses them directly in a queryset slice. A negative `offset` or `limit` from the LLM can produce unsupported negative slicing instead of a useful retryable response, while `limit=0` is silently treated as the default because of `limit or DEFAULT_LIST_LIMIT`.

**Suggestion:** Add numeric constraints to `ListActionsToolArgs` (`limit` with `ge=1, le=MAX_LIST_LIMIT`, `offset` with `ge=0`) and defensively normalize or raise `ActionToolError` in `list_actions()` before slicing. That keeps direct `_arun_impl` calls and any future internal callers safe too.

**Validation Result:** Valid

**Argumentation:** The issue is valid. `ListActionsToolArgs` only documents the expected range for `limit` and `offset`; it does not enforce it, so negative integers pass Pydantic validation. `list_actions()` then computes `start = offset or 0` and `capped_limit = min(limit or DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT)`, which means negative offsets and negative limits are used in the queryset slice and can raise Django's unsupported negative-indexing error instead of a retryable tool error. Explicit `limit=0` is also treated as omitted and returns the default page size, which contradicts the documented 1-100 bound. This can make the Max tool fail noisily from malformed LLM arguments or direct `_arun_impl` calls, so schema constraints plus defensive normalization/rejection in `list_actions()` should be added.

**Category:** bug

---

#### ✅ Issue 2-1-1: Object-specific action editor grants are blocked before object access is checked

**Priority:** should_fix

**File:** `ee/hogai/tools/actions/tool.py` (lines [LineRange(start=113, end=126), LineRange(start=137, end=154)])

**Issue:** `UpdateActionTool` and `DeleteActionTool` require resource-level `action` editor access before `_arun_impl` runs. That is stricter than the REST `AccessControlPermission` contract, which allows non-create writes when the user either has resource-level editor access or has a specific object-level editor grant, followed by `has_object_permission` on the target object. A user with project-wide action viewer access plus editor access to one action can update that action through the REST API, but Max will deny the tool before `_fetch_action()` and `check_object_access()` can evaluate the object grant.

**Suggestion:** Mirror the REST permission flow for object-scoped writes: keep `CreateActionTool` resource-editor-only, but for update/delete replace the unconditional `get_required_resource_access()` editor gate with a tool-layer check equivalent to `check_access_level_for_resource("action", "editor") or has_any_specific_access_for_resource("action", "editor")`, then fetch the target action and keep the existing `check_object_access(action, "editor", ...)` call. Add a test for a user with resource-level viewer and object-level editor on a single action.

**Validation Result:** Valid

**Argumentation:** The issue is valid. `UpdateActionTool` and `DeleteActionTool` declare `get_required_resource_access()` as `[('action', 'editor')]`, and `MaxTool._run/_arun` calls `_check_resource_access()` before `_arun_impl` or the dangerous-operation preview runs. That preflight uses only `UserAccessControl.check_access_level_for_resource`, so a user with resource-level `action` viewer access plus object-specific editor access to the target action is denied before `_fetch_action()` and the existing `check_object_access(action, 'editor', ...)` can evaluate the object grant. The REST permission flow is less strict for non-create writes: `AccessControlPermission.has_permission` allows either resource-level editor access or any specific editor grant for that resource type, then `has_object_permission` checks the target object. This creates an RBAC behavior mismatch where a user can update/delete the action through the REST API but not through Max. The suggested shape is appropriate: keep create gated on resource-level editor, but make update/delete preflight allow resource editor or any specific action editor grant, then rely on the existing object-level check for the fetched action. Risk if left unfixed is legitimate object-scoped editors being unable to manage actions through the AI tool surface, causing inconsistent authorization semantics and user-facing denial for permitted operations.

**Category:** bug

---

#### ✅ Issue 2-1-2: Replacing action steps is an unapproved destructive agent operation

**Priority:** should_fix

**File:** `ee/hogai/tools/actions/tool.py` (lines [LineRange(start=116, end=127)])

**Issue:** `UpdateActionTool` sends updates directly to `update_action`, and the core layer replaces all existing `action.steps` whenever `steps` is provided. Changing an action definition affects every insight, funnel, or other saved object that references that action, and `steps=[]` can effectively wipe the action definition. Unlike `DeleteActionTool`, this destructive Max operation does not require a fresh approval, so an LLM mistake or indirect instruction in prior tool output can mutate analytics semantics without the explicit confirmation used elsewhere for dangerous operations.

**Suggestion:** Add `is_dangerous_operation` and `format_dangerous_operation_preview` to `UpdateActionTool` at least when `steps is not None`, showing the current action and proposed replacement before approval. If the approval payload includes `steps`, also make the approval serialization handle lists of `ActionStepInput` by converting nested Pydantic models to plain dicts.

**Validation Result:** Valid

**Argumentation:** The issue is valid. UpdateActionTool currently treats every update as an ordinary editor operation, but ee/hogai/tools/actions/core.py replaces the entire action.steps collection whenever steps is not None, including steps=[]. Action definitions are reusable analytics primitives, so replacing or clearing steps can silently change the meaning of existing insights, funnels, and other saved references. DeleteActionTool already uses the dangerous-operation approval flow for a similarly destructive change, so step replacement should require the same fresh user confirmation with a preview of the existing and proposed definitions. If that approval is added, the payload path also needs attention: MaxTool._serialize_kwargs_for_storage only dumps top-level BaseModel values, so a list[ActionStepInput] in steps would leave nested Pydantic objects in the approval payload instead of plain JSON-compatible dicts.

**Category:** security

---

#### ✅ Issue 3-1-1: List output is not actually bounded by the action limit

**Priority:** should_fix

**File:** `ee/hogai/tools/actions/core.py` (lines [LineRange(start=124, end=134), LineRange(start=160, end=160)])

**Issue:** `MAX_LIST_LIMIT` caps the number of actions returned, but each listed action still includes the full description and a formatted summary of every step. Action descriptions are `TextField`s and `steps_json` can contain many long selectors, URLs, hrefs, or text values, so `list_actions(limit=100)` can still produce a very large tool response and blow up Max's context despite the intended pagination cap.

**Suggestion:** Make list rendering compact and size-bounded: truncate descriptions and individual step fields, show only a small number of step summaries in non-detailed mode, and append something like `... N more steps` when omitted. Keep `get_action` as the path for fuller details, but consider applying per-field truncation there and in delete previews as well so approval payloads stay bounded.

**Validation Result:** Valid

**Argumentation:** The issue is valid. In ee/hogai/tools/actions/core.py, MAX_LIST_LIMIT only limits the number of Action rows fetched. Each row is then rendered by _format_action without any size bound: description is an unbounded TextField, steps_json is an unbounded JSONField, and non-detailed list output still joins every step summary for every listed action. _format_step also includes raw URL, selector, text, href, and event values without truncation. Since MaxTool returns the string content directly and the tests only verify the row cap, list_actions(limit=100) can still produce an unexpectedly large tool result, increasing token cost or overflowing the assistant context. The same formatter is used for get/create/update responses and delete approval previews, so those paths can also produce oversized payloads, although list_actions is the clearest mismatch with the PR's bounded-listing claim.

**Category:** performance

---

#### ✅ Issue 3-1-2: Create and update accept unbounded step payloads before synchronous bytecode compilation

**Priority:** should_fix

**File:** `ee/hogai/tools/actions/core.py` (lines [LineRange(start=67, end=83), LineRange(start=201, end=204), LineRange(start=222, end=225)])

**Issue:** The tool schemas allow an arbitrary number of action steps, arbitrary numbers of property filters, and unbounded step string fields. `create_action` and `update_action` then convert the full payload and call `Action.save()`, which synchronously refreshes bytecode for the full action definition. A large or accidental LLM tool call can spend significant CPU/memory compiling a huge OR expression, persist an oversized `steps_json`, and echo the result back into the agent context.

**Suggestion:** Add explicit tool-level bounds before saving, for example constants for maximum steps per action, maximum property filters per step, and maximum lengths for selector/text/href/url/event fields. Enforce them with Pydantic `Field(max_length=...)` where possible and defensive `ActionToolError` validation in `create_action`/`update_action`, so oversized payloads become retryable tool errors instead of expensive saves.

**Validation Result:** Valid

**Argumentation:** The issue is valid. `ActionStepInput` and the create/update argument schemas accept `steps` as an unbounded list, `properties` as an unbounded `list[dict]`, and step string fields without length limits. `create_action` and `update_action` then materialize the entire payload into `action.steps` and call `Action.save()`, whose `refresh_bytecode()` synchronously builds an expression and bytecode from all steps. `steps_to_expr()` constructs an OR expression over every step and recursively processes all property filters, so a very large tool payload can consume significant CPU and memory before persisting a large `steps_json`. The detailed create/update response also formats every step and can push large strings back into the agent context. This should be bounded at the tool schema and defensively validated before `Action.save()` so oversized inputs fail as retryable tool errors instead of expensive synchronous work.

**Category:** performance

---

## Chunk 2

### Overview

**Type:** configuration

**Files:**

- `ee/hogai/tools/__init__.py`
- `ee/hogai/chat_agent/toolkit.py`
- `posthog/schema_enums.py`
- `frontend/src/queries/schema/schema-assistant-messages.ts`
- `frontend/src/queries/schema.json`

**Key Changes:**

- Registers the new action tools in the lazy tool export map and DEFAULT_TOOLS so Max can invoke them.
- Adds the action tool names to the assistant tool enum/schema contract used by backend validation and frontend typing.
- Includes generated schema updates required for the new tool names to be recognized consistently.

### Analysis

**Goal:** This configuration chunk wires the new action CRUD MaxTools into the existing HogAI tool system. `ee/hogai/tools/__init__.py` adds `ListActionsTool`, `GetActionTool`, `CreateActionTool`, `UpdateActionTool`, and `DeleteActionTool` to the lazy export map, `__all__`, and type-checking imports, so package-level imports resolve without eagerly loading every tool module. That follows the existing PEP 562 lazy-import pattern used to avoid tool import cycles and Django startup cost while keeping individual tools discoverable from `ee.hogai.tools`.

`ee/hogai/chat_agent/toolkit.py` imports the five classes and adds them to `DEFAULT_TOOLS`. `AgentToolkitManager` instantiates these common tools for normal chat-agent execution, and `DEFAULT_TOOLS` is also used in prompt/switch-mode descriptions, so the action tools become part of Max's common execution tool surface across non-plan agent modes. Execution still flows through `MaxTool`, where the action tool implementations provide resource-level access requirements and object-level checks; delete also participates in the dangerous-operation approval flow. The existing PR discussion flags one unresolved integration concern: this wiring exposes action capabilities through the conversation endpoint, while token-level `action:read` and `action:write` scopes are not carried into tool execution by this chunk.

`posthog/schema_enums.py`, `frontend/src/queries/schema/schema-assistant-messages.ts`, and `frontend/src/queries/schema.json` update the shared `AssistantTool` contract with the five new tool names. This is required because `MaxTool.__init_subclass__` validates backend tool names against `posthog.schema.AssistantTool`, and the frontend Max UI/types consume the generated assistant-message schema for typed tool calls. These schema updates keep backend registration, runtime tool-call validation, and frontend typing synchronized with the new action tool names.

### Issues and Validations

#### ✅ Issue 2-2-1: Mutating action tools become available to subagents despite read-only subagent toolkits

**Priority:** must_fix

**File:** `ee/hogai/chat_agent/toolkit.py` (lines [LineRange(start=58, end=62)])

**Issue:** Adding create_action, update_action, and delete_action to DEFAULT_TOOLS exposes them through ChatAgentToolkit, which AgentToolkitManager combines with every mode toolkit, including subagent runs. Subagent mode only swaps the mode-specific toolkit to read-only variants; it does not replace the common ChatAgentToolkit. That means autonomous subagents can now create or update persistent project actions even though the existing subagent presets explicitly exclude dangerous write tools such as UpsertDashboardTool, UpsertAlertTool, CreateSurveyTool, and EditSurveyTool.

**Suggestion:** Keep read-only action discovery tools in the common/default toolkit if needed, but gate mutating action tools out when context_manager.is_subagent is true, or move create/update/delete into non-subagent execution-mode toolkits instead of DEFAULT_TOOLS. Add a test that builds tools with RunnableConfig(configurable={"is_subagent": True}) and asserts create_action, update_action, and delete_action are absent.

**Validation Result:** Valid

**Argumentation:** The issue is valid. `ChatAgentToolkit.tools` returns `DEFAULT_TOOLS`, and `AgentToolkitManager.get_tools` always combines that agent toolkit with the current mode toolkit. In subagent runs, `ChatAgentModeManager` switches the mode registry to subagent/read-only mode toolkits, but `toolkit_class` still returns `ChatAgentToolkit`, so `ListActionsTool`, `GetActionTool`, `CreateActionTool`, `UpdateActionTool`, and `DeleteActionTool` remain available to the subagent. This undermines the intended subagent capability boundary: create/update actions are persistent writes and are not gated by the dangerous-operation approval flow, while delete is still advertised/executable up to the approval boundary. This is not an RBAC bypass because the tools still require action editor access, but it lets autonomous subagents mutate project actions despite the read-only subagent presets excluding comparable write tools. The mutating action tools should be gated out for `context_manager.is_subagent` or moved into non-subagent execution-mode toolkits, with a regression test asserting they are absent for `RunnableConfig(configurable={"is_subagent": true})`.

**Category:** security

---

## Chunk 3

### Overview

**Type:** frontend

**Files:**

- `frontend/src/scenes/max/max-constants.tsx`

**Key Changes:**

- Adds Max UI metadata for the new action tools, including names, descriptions, icons, and status labels.
- Ensures tool calls for listing, reading, creating, updating, and deleting actions render coherently in the Max conversation UI.
- Depends on the assistant tool schema additions from chunk 2.

### Analysis

**Goal:** This chunk updates the Max frontend presentation registry so the five new action tools introduced elsewhere in the PR have first-class UI metadata. It imports action-appropriate icons from `@posthog/icons` and adds `TOOL_DEFINITIONS` entries for `list_actions`, `get_action`, `create_action`, `update_action`, and `delete_action`, each with a user-facing name, description, icon, and status formatter. The entries follow the existing `ToolDefinition` pattern, including descriptions that start with the tool name, which matches the local `maxGlobalLogic` test convention.

Architecturally, `frontend/src/scenes/max/max-constants.tsx` is the static display contract between backend assistant tool names and the Max conversation UI. Backend `MaxTool` calls arrive in assistant messages as string tool names; `maxThreadLogic` computes their execution status, `toolCallDisplay.ts` resolves the corresponding `ToolDefinition`, and `Thread.tsx` renders the resulting label and icon in `AssistantActionComponent`. These new definitions mean action CRUD calls render as polished statuses such as `Creating action "Signup"...` or `Listed actions` rather than falling back to generic `Executing create_action` text with the default wrench icon.

The chunk depends on the generated assistant schema change that adds these tool names to the `AssistantTool` union; because `TOOL_DEFINITIONS` is typed as `Record<AssistantTool, ToolDefinition>`, the frontend now has compile-time pressure to define metadata for every generated assistant tool. It does not implement execution, permissions, dangerous-operation approval, or action validation; those remain in the backend Max tool layer. The frontend only assumes that create/update tool calls may include an argument named `name`, which is used opportunistically by `skillStatusFormatter` to enrich the display label.

### Issues and Validations

#### ✅ Issue 1-3-1: Action tools are missing from the default tool list

**Priority:** should_fix

**File:** `frontend/src/scenes/max/max-constants.tsx` (lines [LineRange(start=176, end=227)])

**Issue:** The new action tool definitions will make executed tool calls render correctly, but they are not added to `DEFAULT_TOOL_KEYS` and do not declare any `modes`. `ModeSelector` builds the Auto/Plan tooltips from `getDefaultTools()`, which only maps `DEFAULT_TOOL_KEYS`, while mode-specific tooltips use `getToolsForMode()`. Since the backend registers these action CRUD tools in the default toolkit, the frontend tool descriptions will omit capabilities that are actually available.

**Suggestion:** Add `list_actions`, `get_action`, `create_action`, `update_action`, and `delete_action` to `DEFAULT_TOOL_KEYS` if they are intended to be available across all modes. If they should be Product analytics-only, add the appropriate `modes` metadata here and align the backend registration with that behavior.

**Validation Result:** Valid

**Argumentation:** The issue is valid. In frontend/src/scenes/max/max-constants.tsx, the five action tools are present in TOOL_DEFINITIONS but are absent from DEFAULT_TOOL_KEYS and have no modes metadata, so getDefaultTools() and getToolsForMode() cannot surface them in ModeSelector tooltips. The backend ChatAgentToolkit.DEFAULT_TOOLS registers ListActionsTool, GetActionTool, CreateActionTool, UpdateActionTool, and DeleteActionTool as default execution tools, so the UI would under-report capabilities that are actually available. This does not prevent execution or status rendering, but it creates a user-facing capability mismatch and weakens discoverability.

**Category:** bug

---

#### ✅ Issue 2-3-1: Action names are interpolated into Markdown-rendered tool status

**Priority:** must_fix

**File:** `frontend/src/scenes/max/max-constants.tsx` (lines [LineRange(start=200, end=215)])

**Issue:** The create/update action definitions pass `nameArgKey: 'name'`, so `skillStatusFormatter` copies `toolCall.args.name` into the status string. That string is later rendered by `MarkdownMessage`, and action names are LLM/user-controlled strings with no Markdown escaping. A name such as `![x](https://attacker.example/pixel)` would be parsed as an image and auto-load an external URL when the tool call is shown, giving Max tool args an output-rendering exfiltration channel.

**Suggestion:** Escape Markdown metacharacters before adding `rawName` to status text, or stop rendering these status labels as Markdown. A focused fix would add a small inline Markdown escape in `skillStatusFormatter` before building `suffix`, then cover it with a test using an action name like `![x](https://example.test/pixel)` and asserting the rendered status contains text rather than an `img`/link.

**Validation Result:** Valid

**Argumentation:** Valid. The create_action and update_action display formatters pass nameArgKey: "name", skillStatusFormatter reads toolCall.args.name verbatim, and getToolCallDescriptionAndWidgetDef forwards that string into AssistantActionComponent where it is rendered by MarkdownMessage. MarkdownMessage uses LemonMarkdown.Renderer without disableImages, and LemonMarkdown only skips raw HTML; Markdown image syntax such as ![x](https://attacker.example/pixel) will still render as an img tag and trigger a browser request. Action names are accepted as plain strings by the new tool args and stored on Action.name without Markdown escaping, so a model/user-controlled tool argument can become an output-rendering exfiltration channel. CSP does not eliminate this in the main app because the app CSP is emitted as Content-Security-Policy-Report-Only. This should be fixed by escaping Markdown metacharacters for interpolated status labels or by rendering tool status text outside Markdown / with image rendering disabled.

**Category:** security

---
