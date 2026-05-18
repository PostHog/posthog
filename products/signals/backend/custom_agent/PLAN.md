# Custom Signal Agent plan

Status: implementation complete. Core abstraction, repo handling, direct persistence, generic Temporal wrapper, edge-case test coverage, self-documenting base class, and the `CookiePoemAgent` reference example + management command are all in place locally. Pending: commit/PR + production validation.

Target module: `products/signals/backend/custom_agent/`

## Current implementation status

Last updated: 2026-05-18.

Implemented in this pass:

- Patched `create_task_and_trigger()` to forward `sandbox_environment_id` and `posthog_mcp_scopes` from `CustomPromptSandboxContext` into `Task.create_and_run()`.
- Added raw multi-turn support in `MultiTurnSession`:
  - `start_raw()` returns `(session, raw_text)`.
  - `send_followup_raw()` returns raw response text while preserving existing empty-turn retry behavior.
  - Existing structured `start()` / `send_followup()` now wrap the raw helpers.
- Added `products/signals/backend/custom_agent/` modules:
  - `schemas.py`
  - `loader.py`
  - `base.py`
  - `repo_selection.py`
  - `default_resolvers.py`
  - `persistence.py`
  - `__init__.py`
- Implemented `CustomSignalAgent` with:
  - mandatory `(product, type)` identifier validation,
  - top-level import-path generation,
  - lazy session startup,
  - automatic schema prompt wrapping,
  - JSON extraction + Pydantic validation retry loop,
  - typed `CustomAgentValidationError`,
  - manual report-component registration methods,
  - duplicate-registration protection via `overwrite=True`,
  - default missing-component resolvers,
  - session cleanup in `finally`.
- Implemented free-form custom-agent repository resolution:
  - explicit `owner/repo` normalization,
  - `NO_REPO` sentinel mapped to `PostHog/.github` sandbox bootstrap and selected repo `None`,
  - free-form `initial_prompt` repo selector,
  - generic user resolver that can fall back to active org members when no GitHub integration exists.
- Implemented direct ready-report persistence in `persistence.py`:
  - creates `SignalReport(status=READY)` directly,
  - writes compatible `repo_selection`, `actionability_judgment`, `priority_judgment`, and `suggested_reviewers` artefacts,
  - links sandbox task as `SignalReportTask.Relationship.RESEARCH` when present,
  - does not call `SignalReport.transition_to()`.
- Added generic Temporal wrapper in `products/signals/backend/temporal/custom_agent.py` and registered it in `products/signals/backend/temporal/__init__.py`:
  - `CustomAgentWorkflowInput` / `CustomAgentWorkflowOutput`,
  - `CustomSignalAgentWorkflow` named `signals-custom-agent`,
  - `run_custom_signal_agent_activity`,
  - activity-side import and identifier validation,
  - public `CustomSignalAgent.run_agent()` / `arun_agent()` helpers using the shared workflow name.

Tests added / updated:

- Added regression tests for sandbox context forwarding in `products/tasks/backend/tests/test_multi_turn_session.py`.
- Added `products/signals/backend/test/test_custom_agent.py` covering:
  - first-turn validation retry,
  - `validation_retries=0`,
  - fully registered components without starting a session,
  - duplicate registration behavior,
  - loader identity validation,
  - nested class rejection,
  - explicit repo / `NO_REPO` / free-form selected repo modes,
  - direct ready-report persistence,
  - activity import + run + direct persistence.

Validation run so far:

- `uv run pytest products/tasks/backend/tests/test_multi_turn_session.py products/signals/backend/test/test_custom_agent.py products/signals/backend/test/test_agentic_report_activity.py -q`
- Result: `31 passed`.

Added in the latest pass:

- Fixed both `B009` ruff issues in `base.py` (`getattr(team, "id")` → `team.id`).
- Expanded the `CustomSignalAgent` class docstring into a full extender contract / lifecycle / `send()` semantics / repository mode / class attribute guide. The base class is now self-documenting.
- Added the canonical example agent `products/signals/backend/custom_agent/examples/cookie_poem_agent.py` (`CookiePoemAgent`): identifier `(signals, cookie_poem)`, two-step `send()` flow with per-call `validation_retries=2` override on the poem step, manual P0 + immediately_actionable registration on every run, `NO_REPO` mode, empty assignees. Module-level docstring shows the invocation pattern.
- Added Django management command `products/signals/backend/management/commands/run_cookie_poem_agent.py` that calls `CookiePoemAgent.run_agent(team=..., initial_prompt=..., repository=NO_REPO)` with `--team-id`, `--prompt`, `--id`, `--model` flags. Reports `started` vs `already_running` from the returned `CustomAgentRunHandle`.
- Broadened Temporal helper tests for `arun_agent()`: explicit ID, generated UUID, `WorkflowAlreadyStartedError` mapped to `already_running=True`, and primitives-only workflow input shape.
- Added repo edge-case activity tests: "Repository selection required" early-stop path when free-form selection returns no repo, and `continue_without_repository=True` proceeding past missing repo.
- Added default-resolver tests: missing components resolve in order, finalization context is included exactly once across all resolver turns, `not_actionable` skips priority resolution, registered fields survive resolution.
- Added persistence edge-case tests: `SUGGESTED_REVIEWERS` artefact with mixed `str` / `dict` / `CustomAgentAssignee` input (deduped and lowercased), and atomicity — a failure mid-artefact-bulk-create rolls back the report and writes nothing.

Known follow-ups (out of scope for v1):

- Pyright still complains about `team.id` on the Django `Team` model and `SimpleNamespace` test fakes not satisfying the `Team` type. Pre-existing codebase pattern; ruff/tests are the source of truth.
- Phase 8-ish polish like `SignalReport.metadata` for product/type persistence (called out below under "Decisions to revisit after v1").

Operational handoff notes for the next implementation session:

- Current work is local and uncommitted.
- Before this status update, `git status --short` showed modified tracked files plus new untracked custom-agent files. Expected modified/new paths now include:
  - `products/signals/backend/custom_agent/PLAN.md`
  - `products/signals/backend/temporal/__init__.py`
  - `products/tasks/backend/services/custom_prompt_internals.py`
  - `products/tasks/backend/services/custom_prompt_multi_turn_runner.py`
  - `products/tasks/backend/tests/test_multi_turn_session.py`
  - `products/signals/backend/custom_agent/`
  - `products/signals/backend/temporal/custom_agent.py`
  - `products/signals/backend/test/test_custom_agent.py`
- This repo should be run through flox. Plain `pytest` was not available in the activated environment; use `uv run pytest` inside `flox activate -- bash -c "..."`.
- The exact focused validation command that passed was:
  - `flox activate -- bash -c "uv run pytest products/tasks/backend/tests/test_multi_turn_session.py products/signals/backend/test/test_custom_agent.py products/signals/backend/test/test_agentic_report_activity.py -q"`
  - Result: `41 passed`.
- The full custom/multi-turn focused test command also passed:
  - `flox activate -- bash -c "uv run pytest products/tasks/backend/tests/test_multi_turn_session.py products/signals/backend/test/test_custom_agent.py -q"`
  - Result: `35 passed`.
- Management command sanity check:
  - `flox activate -- bash -c "uv run python manage.py run_cookie_poem_agent --help"` prints help and lists the four flags.
- Syntax/compile validation passed with:
  - `flox activate -- bash -c "python3 -m compileall products/signals/backend/custom_agent products/signals/backend/temporal/custom_agent.py products/tasks/backend/services/custom_prompt_internals.py products/tasks/backend/services/custom_prompt_multi_turn_runner.py"`
- Ruff command to rerun after cleanup:
  - `flox activate -- bash -c "uv run ruff check products/signals/backend/custom_agent products/signals/backend/temporal/custom_agent.py products/signals/backend/test/test_custom_agent.py products/tasks/backend/services/custom_prompt_internals.py products/tasks/backend/services/custom_prompt_multi_turn_runner.py products/tasks/backend/tests/test_multi_turn_session.py"`
- Ruff is clean across all touched files.
- Best pickup sequence for the next session:
  1. `git status --short` to confirm local changes match the list above.
  2. Rerun the ruff and pytest commands above to confirm green.
  3. Decide on commit/PR strategy (single commit vs phases).
  4. Pilot a real run through the management command in a sandbox-enabled environment to validate end-to-end Temporal + sandbox + persistence.

Implementation gotchas from the first pass:

- Do not pass `NO_REPO` to `Task.repository`; `resolve_custom_agent_repository()` translates it to the `PostHog/.github` sandbox bootstrap repository.
- Do not persist `PostHog/.github` as the selected repo for `NO_REPO` runs.
- `CustomSignalAgent.start()` ends the session in `finally`; if no `send()` happened, no task/session exists and nothing is linked.
- `create_custom_agent_ready_report()` links a task only when `agent.task` exists.
- Product/type metadata is not persisted yet because `SignalReport` has no metadata field; workflow input/ID and logs carry it for now.
- `default_resolvers.py` uses a protocol instead of importing `CustomSignalAgent` to avoid import cycles.
- Workflow DTOs live in `schemas.py` so `base.py` does not need to import `temporal/custom_agent.py`.
- `CustomSignalAgent.arun_agent()` starts the Temporal workflow by workflow name string (`signals-custom-agent`) instead of importing the workflow class, also to avoid import cycles.
- The generic activity runs on the shared Signals worker registration path via `products/signals/backend/temporal/__init__.py`.
- `repository=NO_REPO` passed to public `run_agent()` is safe because it remains a Temporal input string until activity-side repository resolution translates it before task creation.

## Updated decisions

- Custom agents need a free-form repository selector driven by `initial_prompt`; the existing selector is signal-shaped and should not be reused unchanged.
- `send()` owns structured-output validation. If JSON extraction or Pydantic validation fails, `send()` sends the validation error back to the agent and gives it another chance. Default validation retries: 3. Callers can override per call, including `0` retries.
- Custom-agent report persistence should create final `READY` reports directly. Do not use `SignalReport.transition_to()` or the existing candidate/in-progress pipeline transitions.
- There is one generic custom-agent Temporal workflow maintained by the Signals team. It runs on the same workers/task queue as the existing Signals pipeline.
- Extenders should not manually register agent classes. `run_agent()` should capture an importable class path automatically; the generic workflow activity imports that class and validates its `(product, type)` identifier.

## Goal

Build a Signals-backed custom agent abstraction that PostHog engineers can extend with minimal boilerplate while still getting the hard parts of the current signal report research pipeline for free:

- Repository selection before the research session starts.
- A simple multi-turn `send()` API backed by `MultiTurnSession`.
- Automatic JSON schema injection, structured validation, and validation-error retry loops.
- Manual registration hooks for final report components.
- Default post-run resolution for missing report components.
- Atomic persistence into the existing `SignalReport` / `SignalReportArtefact` / `SignalReportTask` model set so the report appears in the PostHog Code Inbox.
- A fire-and-forget Temporal `run_agent` interface with deterministic workflow IDs based on a mandatory `(product, type)` identifier.

The intended extender experience is:

- Subclass `CustomSignalAgent`.
- Implement a mandatory identifier method returning `(product, type)`.
- Override `run()` for the middle research logic.
- Inside `run()`, call `await self.send(prompt, OutputModel)` as many times as needed.
- Optionally override `validation_retries` per `send()` call when a specific step should be stricter or more lenient.
- Call `register_title`, `register_description`, `register_assignees`, `register_actionability`, and/or `register_priority` when known.
- Start the agent with `MyAgent.run_agent(team=team, initial_prompt=..., repository=...)` and do not worry about Temporal, repo selection, class registration, report persistence, or final missing-field prompts.

## Existing code reviewed and constraints discovered

### Multi-turn task infra

Relevant files:

- `products/tasks/backend/services/custom_prompt_multi_turn_runner.py`
- `products/tasks/backend/services/custom_prompt_internals.py`
- `products/tasks/backend/models.py`
- `products/tasks/backend/services/mts_example/runner.py`

Findings:

- `MultiTurnSession.start()` creates a `Task`, starts the task processing workflow, waits for the first agent turn, extracts JSON, and validates it against a Pydantic model.
- There is no “start session without a model” API. The first custom-agent `send()` should lazily call into session startup, and later sends should call `session.send_followup()`.
- Existing callers manually include JSON schema text in prompts. `MultiTurnSession` does not inject schemas. The custom abstraction should make `send(prompt, model)` append a schema and JSON-only instruction consistently.
- Current `MultiTurnSession.start()` validates before returning the session. To support “validation failed → tell the LLM → retry” on the first turn, we need either a small lower-level API such as `MultiTurnSession.start_raw()` or a custom-agent session wrapper that uses `create_task_and_trigger()` and `poll_for_turn()` directly before validating.
- `send_followup()` already retries once for empty `end_turn` responses. That is separate from schema-validation retries. Validation retries should happen after receiving non-empty text that fails JSON extraction or Pydantic validation.
- `MultiTurnSession.end()` should be called in a `finally` block for the custom abstraction once a session exists. Existing research code only ends on success; for reusable infra, we should be stricter.
- `CustomPromptSandboxContext` has `sandbox_environment_id`, `posthog_mcp_scopes`, and `model`, but `create_task_and_trigger()` currently does not pass `sandbox_environment_id` or `posthog_mcp_scopes` into `Task.create_and_run()`. That means today a `MultiTurnSession` context that says `posthog_mcp_scopes="read_only"` can still rely on defaults rather than the explicit context. Fix this before depending on custom sandbox envs or read-only MCP scopes.
- `Task.create_and_run()` validates `repository` as `owner/repo`. The sentinel `NO_REPO` must never be passed as `Task.repository`; translate it to the dummy sandbox repo first.
- `PostHog/.github` is already a public sandbox repo allowed by `products/tasks/backend/services/sandbox.py`, which makes it usable without a GitHub integration.

### Current Signals report generation

Relevant files:

- `products/signals/backend/report_generation/research.py`
- `products/signals/backend/report_generation/select_repo.py`
- `products/signals/backend/temporal/agentic/report.py`
- `products/signals/backend/temporal/agentic/select_repository.py`
- `products/signals/backend/temporal/summary.py`
- `products/signals/backend/models.py`
- `products/signals/backend/serializers.py`
- `products/signals/backend/views.py`

Findings:

- Current summary flow is safety judge → repo selection → agentic research → state transition. Custom agents reuse the useful concepts but do not participate in that status machine.
- Current repo selection is implemented for signal reports and expects `list[SignalData]`. It renders source product/type, signal weight, timestamp, description, and optional extras. A custom agent starts from a free-form `initial_prompt`, so it needs a free-form repo selector rather than faking a `SignalData` record.
- Existing repo selection uses `PostHog/.github` as a dummy clone because the selection agent only needs `gh` and SQL/MCP access, not the target repo clone.
- Existing report research stores compatible Pydantic models we should reuse:
  - `ActionabilityAssessment`
  - `ActionabilityChoice`
  - `PriorityAssessment`
  - `Priority`
  - `ReportPresentationOutput`
- Code Inbox reads report display data from `SignalReport.title`, `SignalReport.summary`, and artefacts. There is no `description` field on `SignalReport`; custom agent `register_description()` maps to `SignalReport.summary`.
- Suggested assignee/reviewer UI behavior is currently driven by `SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS`. Content must be valid JSON shaped as a list of objects, normally with `github_login`, `github_name`, and `relevant_commits`.
- For custom agents, do not use `SignalReport.transition_to()`. Create completed reports directly with `status=SignalReport.Status.READY`, final title, final summary, and final artefacts.
- Custom-agent reports may have no ClickHouse signals. They will still display in the report list, but `source_products` and `/signals` will be empty. That is acceptable for v1; filtering by source product can come later via metadata or synthetic signals.

### Temporal pattern

Relevant files:

- `products/signals/backend/temporal/__init__.py`
- `products/signals/backend/temporal/grouping.py`
- `products/tasks/backend/temporal/client.py`

Findings:

- Signals workflows and activities are explicitly registered in `products/signals/backend/temporal/__init__.py`. The single custom-agent workflow and activity must be added there.
- There should be exactly one generic custom-agent workflow maintained by the Signals team. Concrete agents do not define their own Temporal workflows.
- The workflow runs on the same workers/task queue as the rest of the Signals pipeline: `settings.VIDEO_EXPORT_TASK_QUEUE` through the existing Signals worker registration.
- Workflow inputs should be primitive/data-class serializable values: `team_id`, `agent_path`, `product`, `type`, `initial_prompt`, `repository`, `run_id`, etc. Do not pass Django `Team` objects or Python classes through Temporal.
- The public API can accept a `Team` instance, but the workflow input should contain `team_id`.
- The long-running activity that owns the custom agent should use a single attempt by default. Retrying a sandbox-backed multi-turn session can create duplicate tasks and conversations unless persistence and task creation are made idempotent.

## Why custom agents need free-form repo selection

The existing repo selector is “signal-shaped” in both input and prompt semantics:

- It accepts `list[SignalData]`, not arbitrary text.
- It renders each item with source product, source type, weight, timestamp, and description via `render_signals_to_text()`.
- Its prompt tells the LLM that “the signals below describe issues, feature requests, bugs, or observations reported by users.”
- Its decision rule is to choose the repository that is the most likely subject of those signals.

That is correct for the current Signals pipeline, but it is a bad fit for custom agents because an `initial_prompt` might be any of these:

- “Find stale feature flags related to billing and write a cleanup report.”
- “Audit our dashboard code for confusing empty states.”
- “Research whether surveys have broken mobile layout handling.”
- “Run a no-repo MCP-only investigation into product analytics data.”

Faking those as a single `SignalData` object would inject misleading metadata:

- Fake `source_product` / `source_type` values would become accidental evidence.
- Fake `weight` and timestamp would imply signal ranking semantics that do not exist.
- The prompt would keep saying the input is a user-reported signal, even when the request is an engineer-authored investigation.
- Repo selection would optimize for “where would a developer address this signal?” instead of “which repository should this custom agent use as its working context for this request?”

The free-form selector should preserve the useful mechanics from current repo selection while changing the input semantics:

- Input is the exact `initial_prompt`.
- The prompt says this is the user/request context for a custom research agent.
- It still lists candidate repos and uses the heavy repository cache as evidence.
- It still uses `PostHog/.github` as the lightweight dummy sandbox repo.
- It still returns a structured repo selection result.
- The same `initial_prompt` is then included in the research agent’s first context so the request is not lost after repo selection.

## Proposed module layout

Create a package at `products/signals/backend/custom_agent/`:

- `__init__.py`
  - Public exports: `CustomSignalAgent`, `NO_REPO`, `CustomAgentRunHandle`, and reusable schema aliases.

- `base.py`
  - `CustomSignalAgent` base class.
  - Lifecycle orchestration: repo resolution, `run()`, default post-run resolution, final validation, direct ready-report persistence.
  - `send()` wrapper over `MultiTurnSession` with lazy first-turn creation, schema injection, validation retry, and session cleanup.
  - `register_title`, `register_description`, `register_assignees`, `register_actionability`, `register_priority`.
  - Public `run_agent()` / `arun_agent()` class methods.

- `schemas.py`
  - Custom agent Pydantic models:
    - `CustomAgentIdentifier`
    - `CustomAgentAssignee`
    - `CustomAgentAssigneesOutput`
    - `CustomAgentRepositorySelectionResult`
    - `CustomAgentReportComponents`
    - `CustomAgentRunHandle`
    - `CustomAgentRunResult`
  - Re-export or alias existing Signals schemas where appropriate:
    - `ActionabilityAssessment`
    - `ActionabilityChoice`
    - `PriorityAssessment`
    - `Priority`
    - `ReportPresentationOutput`

- `default_resolvers.py`
  - Standalone default component resolvers:
    - `resolve_title(agent)`
    - `resolve_description(agent)`
    - `resolve_assignees(agent)`
    - `resolve_actionability(agent)`
    - `resolve_priority(agent)`
  - Prompt builders for each resolver.
  - The first default resolver invoked includes final report preparation context.

- `repo_selection.py`
  - Free-form repo selection based on `initial_prompt`.
  - Reuse lower-level helpers and constants from `report_generation/select_repo.py` where possible.
  - Normalize explicit repo values.
  - Translate `NO_REPO` to `PostHog/.github` for sandbox execution while preserving “no selected subject repo” in report data.

- `persistence.py`
  - Create final `READY` `SignalReport` rows directly.
  - Persist compatible artefacts atomically.
  - Link the underlying sandbox `Task` via `SignalReportTask(relationship=RESEARCH)` after the report is created.

- `loader.py`
  - Import and validate the concrete agent class from the dotted class path captured by `run_agent()`.
  - Validate the imported class is a top-level importable `CustomSignalAgent` subclass.
  - Validate imported class identifier matches workflow input `(product, type)`.
  - This replaces manual registration for v1.

- `products/signals/backend/temporal/custom_agent.py`
  - One generic workflow and one generic activity maintained by the Signals team:
    - `RunCustomAgentInput`
    - `RunCustomAgentOutput`
    - `CustomSignalAgentWorkflow`
    - `run_custom_signal_agent_activity`
  - The activity imports and runs the concrete agent via `custom_agent.loader`.

- `README.md` or `AGENTS.md` later
  - Extension guide with examples after implementation lands.

## Public interface design

### Mandatory identifier

Each subclass must provide a `(product, type)` identifier. This must be available at class level because `run_agent()` needs it before the Temporal workflow starts.

Proposed shape:

- `@classmethod def identifier(cls) -> tuple[str, str]`
- `product` and `type` values should be slug-like strings: lowercase letters, numbers, underscores, or hyphens.
- The base class validates that the subclass overrides this method and that neither component is empty.
- The identifier is used for:
  - Workflow ID generation.
  - Runtime class validation after the workflow activity imports the class.
  - Future report metadata.
  - Analytics/log tags.

### Seamless class loading, no manual registration

Extenders should not need to register their classes.

The plan:

- `MyAgent.run_agent(...)` computes `agent_path` from `MyAgent.__module__` and `MyAgent.__qualname__`.
- `run_agent()` validates that the class is top-level importable. Nested/local classes are rejected with a clear error.
- Workflow input includes `agent_path`, `product`, and `type`.
- The generic activity imports the class from `agent_path` using a safe import helper.
- The activity verifies:
  - imported object is a `CustomSignalAgent` subclass,
  - imported class identifier exactly matches workflow input `(product, type)`.

This avoids a manual registry and avoids requiring worker startup to import every possible custom agent module in advance. The only practical requirement for extenders is to define the class in an importable module, which is normal Python.

### Constructor inputs

The activity instantiates the agent with:

- `team: Team`
- `initial_prompt: str`
- `repository: str | None`
- `run_id: str`
- Optional `branch: str | None`
- Optional `model: str | None`
- Optional `verbose: bool`
- Optional `output_fn`

Only `team`, `initial_prompt`, optional `repository`, and optional run ID are part of the public user-facing API. The rest are system options.

### `run()` contract

Subclasses implement:

- `async def run(self) -> None`

Inside `run()`, they can:

- Call `await self.send(prompt, OutputModel, label="...")` to ask the underlying agent for structured output.
- Pass `validation_retries=0` or another integer to override validation retry behavior for that call.
- Call `self.register_title(...)` when they know the final title.
- Call `self.register_description(...)` when they know the final Code Inbox summary/description.
- Call `self.register_assignees(...)` when they know reviewers/owners.
- Call `self.register_actionability(...)` when they know actionability.
- Call `self.register_priority(...)` when they know priority.

`run()` should not persist reports and should not start Temporal workflows.

### `send()` contract

Proposed signature:

- `async def send(self, prompt: str, output_model: type[T], *, label: str | None = None, include_report_context: bool = True, validation_retries: int | None = None) -> T`

Default behavior:

- `validation_retries=None` uses `self.default_validation_retries`, initially `3`.
- `validation_retries=0` means validate once and raise immediately if it fails.
- Negative values are invalid.

Prompt behavior:

- First `send()` lazily starts the underlying multi-turn session.
- Later sends use `session.send_followup()`.
- The first prompt includes:
  - A custom-agent system preamble.
  - The `initial_prompt` as the user/request context.
  - The selected repository context, or explicit “no selected subject repo” context.
  - Safety instructions that repository content, data, and user text are untrusted evidence.
  - The extender’s prompt.
  - The JSON schema for `output_model`.
- Later prompts include the extender’s prompt and schema, plus any requested report/component context.

Validation retry behavior:

- `send()` receives raw agent text.
- It attempts JSON extraction and Pydantic validation.
- If validation succeeds, it returns the validated model.
- If validation fails and retries remain, it sends a follow-up containing:
  - “Your previous response did not match the required JSON schema.”
  - The concise validation/parsing error.
  - The required schema again.
  - “Return only a JSON object matching the schema.”
- It repeats until validation succeeds or attempts are exhausted.
- If attempts are exhausted, raise a typed `CustomAgentValidationError` that includes label, model name, validation errors, and last raw text.

Implementation implication:

- Current `MultiTurnSession.start()` cannot implement first-turn validation retry because it raises before returning the session. Add a raw-start helper or custom-agent-specific session wrapper before implementing this API.

### Register functions

Use existing Signals-compatible output schemas wherever possible.

- `register_title(title: str) -> None`
  - Maps to `SignalReport.title`.
  - Validate non-empty and length reasonable for Code Inbox.

- `register_description(description: str) -> None`
  - Maps to `SignalReport.summary`.
  - Name remains `description` for extender ergonomics, but documentation must state that persistence writes `SignalReport.summary`.

- `register_assignees(assignees: list[CustomAgentAssignee] | list[str]) -> None`
  - Common case: list of GitHub logins as strings.
  - Normalize GitHub logins to lowercase.
  - Persist as `SUGGESTED_REVIEWERS` artefact if non-empty.
  - Support richer objects for `github_login`, `github_name`, and `relevant_commits`.

- `register_actionability(actionability: ActionabilityAssessment | ActionabilityChoice | str, *, explanation: str | None = None, already_addressed: bool = False) -> None`
  - Store as current `ActionabilityAssessment` shape.
  - If given only enum/string, require or synthesize a clear explanation.

- `register_priority(priority: PriorityAssessment | Priority | str, *, explanation: str | None = None) -> None`
  - Store as current `PriorityAssessment` shape.
  - If actionability is `not_actionable`, priority may remain `None` by default.

Duplicate registration default:

- Make duplicate registrations explicit. Either raise on duplicate by default or require `overwrite=True`. Prefer raising by default to catch accidental overwrites.

## Repository behavior

### Input cases

- `repository="owner/repo"`
  - Skip repo selection entirely.
  - Normalize to lowercase for persistence and task creation.
  - Use that repo as the sandbox repo.
  - Store a `repo_selection` artefact with repository and reason “repository provided by caller”.

- `repository=NO_REPO`
  - Skip repo selection entirely.
  - Use `PostHog/.github` as the sandbox repo.
  - Treat selected subject repository as `None` in report data.
  - Store a `repo_selection` artefact with `repository=null` and reason “NO_REPO provided by caller; using PostHog/.github as sandbox bootstrap repository”.
  - Do not persist `.github` as the selected report repo.

- `repository=None`
  - Run free-form repository selection before any research `send()` happens.
  - Use `initial_prompt` as the source text for repo selection.
  - If a repo is selected, use it as the sandbox repo and persist it as selected repo.
  - If no repo is selected, default v1 behavior should be to create a final `READY` “Repository selection required” report with actionability `requires_human_input`, then stop before subclass `run()`. Subclasses can override this to continue with `NO_REPO`.

### Free-form repo selection

Custom agents need a sibling function to the current signal report selector:

- `select_repository_for_prompt(team_id, user_id, initial_prompt, sandbox_environment_id=None, verbose=False, output_fn=None) -> CustomAgentRepositorySelectionResult`

Implementation notes:

- Reuse `resolve_team_github_integration`, candidate repo listing, heavy cache hydration, eligible repo filtering, and dummy repo constant from `report_generation/select_repo.py` where possible.
- Build a prompt around “the custom agent’s initial request” rather than “signals”.
- Keep the cache-query rules from current repo selection: SQL evidence is primary when multiple repos plausibly match.
- Continue using `PostHog/.github` for the repo-selection sandbox clone.
- Repo selection itself should run in the restricted GitHub-only sandbox environment, like the current Signals repo selector.
- The `initial_prompt` must also be included later in the research agent context. Repo selection consuming the prompt must not make the prompt disappear from the actual agent run.

### User resolution for no-repo agents

Current `resolve_user_id_for_team()` assumes a GitHub integration exists. For `NO_REPO` and repo-less defaults, add a generic user resolver:

- Prefer GitHub integration creator when a GitHub integration is available.
- Otherwise choose the first active organization member.
- This avoids blocking no-repo custom agents on GitHub installation state.

## Lifecycle

### High-level flow

1. Public `run_agent()` is called with `team`, `initial_prompt`, optional `repository`, and optional `id`.
2. `run_agent()` validates the class identifier, computes `agent_path`, and computes a workflow ID.
3. `run_agent()` starts the one generic `CustomSignalAgentWorkflow` and returns a handle immediately.
4. Workflow executes `run_custom_signal_agent_activity` with a single attempt by default.
5. Activity imports the concrete agent class from `agent_path` and validates its identifier.
6. Activity resolves repository first:
   - explicit repo, `NO_REPO`, or free-form selection from `initial_prompt`.
7. If repo selection returns no repo and the agent does not opt into no-repo continuation, create a final `READY` “Repository selection required” report and stop.
8. Activity instantiates the agent and calls `agent.start()`.
9. Agent `start()` executes subclass `run()`.
10. Post-run resolver checks required final components and prompts for each missing one.
11. Final components are validated.
12. Persistence creates the final `SignalReport(status=READY, title=..., summary=...)` directly.
13. Persistence writes artefacts atomically.
14. If a sandbox session was started, link its `Task` to the report with `SignalReportTask(relationship=RESEARCH)`.
15. Session is ended in `finally` if it was started.

### Report row timing

Do not create a placeholder `SignalReport` at the beginning.

Create the `SignalReport` only after the final report components are available, directly in its final Code Inbox state:

- `team`
- `status=SignalReport.Status.READY`
- `title=final title`
- `summary=final description`
- `signal_count=0`
- `total_weight=0.0`

This avoids using the existing signal pipeline state machine and avoids report transition code entirely.

Task linking still works:

- The sandbox `Task` exists as soon as first `send()` starts a `MultiTurnSession`.
- After creating the final report, create a `SignalReportTask` row linking that task to the report.
- Do not rely on the deprecated `Task.signal_report` field for custom agents.

Failure behavior:

- If the agent fails before a final report exists, do not create a partial report by default.
- The underlying sandbox task/run still contains failure logs.
- Future work can add explicit failed-report persistence if the Code Inbox wants failed custom-agent runs surfaced.

### Session cleanup

`start()` owns the session lifecycle:

- If no `send()` is ever called, no `MultiTurnSession` exists and there is nothing to end.
- If a session exists, `await session.end()` in a `finally` block.
- If `session.end()` fails, log the exception but preserve the original run result/failure.

## Post-run default resolution

The base class should resolve missing components after subclass `run()` finishes.

Required components:

- Title: required.
- Description/Summary: required.
- Actionability: required.
- Priority: required unless actionability is `not_actionable`.
- Assignees: default to empty list if not resolvable, but still expose `resolve_assignees()` as an overridable step.

Resolution order:

1. Title.
2. Description.
3. Actionability.
4. Priority, if needed.
5. Assignees.

Reason for this order:

- Title/description help anchor actionability and priority prompts.
- Assignees are often best derived after the report scope and priority are known.

First missing-component prompt:

- The first default resolver invoked should include a one-time finalization context:
  - “You are now preparing the final PostHog Code Inbox report for the work you just did.”
  - “Use the initial prompt, repository selection, and all research/conversation context so far.”
  - “Do not continue broad research unless strictly needed to fill this report field.”
  - “Return only JSON matching the schema.”

Subsequent default resolver prompts:

- Reference already registered/resolved fields.
- Keep prompts short and schema-specific.

Overriding options:

- Subclass can manually register fields in `run()`; registered fields are never overwritten by default resolvers.
- Subclass can override `resolve_title`, `resolve_description`, `resolve_actionability`, `resolve_priority`, or `resolve_assignees`.
- Subclass can override `resolve_missing_report_components()` for full control.

## Persistence plan

### Direct ready-report creation

Persist a custom-agent report in one transaction after the run succeeds:

- Create `SignalReport` directly with `status=READY`, final title, and final summary.
- Bulk-create compatible artefacts.
- Link any underlying sandbox research task.

Do not call:

- `SignalReport.transition_to()`
- `mark_report_in_progress_activity`
- `mark_report_ready_activity`
- Existing summary workflow activities

### Artefact mapping

Persist only existing artefact types in v1 to avoid a migration for custom metadata.

- Repository selection:
  - Type: `SignalReportArtefact.ArtefactType.REPO_SELECTION`
  - Shape: compatible with `RepoSelectionResult`, `{"repository": str | null, "reason": str}`.

- Actionability:
  - Type: `ACTIONABILITY_JUDGMENT`
  - Shape: current `ActionabilityAssessment`, with `actionability`, `explanation`, and `already_addressed`.

- Priority:
  - Type: `PRIORITY_JUDGMENT`
  - Shape: current `PriorityAssessment`, with `priority` and `explanation`.

- Assignees:
  - Type: `SUGGESTED_REVIEWERS`
  - Shape: list of reviewer dicts with lowercased `github_login`; optional `github_name`; optional `relevant_commits`.

- Signal findings:
  - Do not write `SIGNAL_FINDING` by default because custom agents are not necessarily signal-backed and may not produce one finding per signal.
  - Allow an advanced API later if a custom agent wants to persist findings explicitly.

### Atomicity

- Collect all report fields and artefacts in memory.
- Persist report, artefacts, and task link in one transaction.
- Since v1 creates a new report per run, no artefact replacement is needed.

### Metadata later

The user wants `(product, type)` included in report metadata later. Current `SignalReport` has no metadata field and current artefact types do not include custom metadata.

V1 approach:

- Include product/type/run_id/workflow_id in logs and analytics.
- Include product/type in the workflow ID and Temporal input.
- Do not overload user-visible report content with metadata.

Future migration:

- Add `SignalReport.metadata JSONField(default=dict)` or a new `SignalReportArtefact.ArtefactType.CUSTOM_AGENT_METADATA`.
- Store `product`, `type`, `run_id`, `workflow_id`, `repository_mode`, selected repo, sandbox repo, and a hash of the initial prompt.

## Temporal plan

### One maintained workflow

Add `products/signals/backend/temporal/custom_agent.py`.

Workflow name:

- `signals-custom-agent`

Activity name:

- `run_custom_signal_agent_activity`

Ownership and deployment:

- The Signals team maintains this one generic workflow.
- Concrete custom agents do not define workflows.
- Register the workflow/activity in `products/signals/backend/temporal/__init__.py`.
- Run it on the same Signals workers and task queue as the rest of the Signals pipeline: `settings.VIDEO_EXPORT_TASK_QUEUE`.

Workflow input fields:

- `team_id: int`
- `agent_path: str`
- `product: str`
- `type: str`
- `run_id: str`
- `initial_prompt: str`
- `repository: str | None`
- `branch: str | None = None`
- `model: str | None = None`

Workflow output fields:

- `report_id: str | None`
- `status: str`
- `repository: str | None`
- `task_id: str | None`

### Workflow ID

User requirement:

- Identifier is `(product, type)`.
- Optional ID is appended to this tuple with `-`.
- Otherwise a UUID is used.

Proposed workflow ID format:

- `signals-custom-agent:{team_id}:{product}:{type}-{id_or_uuid}`

Examples:

- Product/type `experiments`, `winner_cleanup`, no ID: `signals-custom-agent:123:experiments:winner_cleanup-550e8400-e29b-41d4-a716-446655440000`
- Product/type `experiments`, `winner_cleanup`, ID `exp-42`: `signals-custom-agent:123:experiments:winner_cleanup-exp-42`

Sanitize `product`, `type`, and optional ID before constructing the workflow ID. Reject or normalize unsafe characters.

### Public start helpers

Expose as `CustomSignalAgent` class methods:

- `async def arun_agent(cls, team: Team, initial_prompt: str, repository: str | None = None, id: str | None = None, **options) -> CustomAgentRunHandle`
- `def run_agent(cls, team: Team, initial_prompt: str, repository: str | None = None, id: str | None = None, **options) -> CustomAgentRunHandle`

`CustomAgentRunHandle` includes:

- `workflow_id`
- `run_id`
- `product`
- `type`
- `team_id`
- `started: bool`
- `already_running: bool`

Fire-and-forget behavior:

- Start the workflow and return immediately.
- Do not wait for workflow completion.
- If the optional ID creates an already-running workflow, catch `WorkflowAlreadyStartedError` and return the same handle with `already_running=True`.

## Implementation phases

Current phase status summary:

- Phase 0: implemented and covered by focused tests.
- Phase 1: implemented and covered by focused tests.
- Phase 2: implemented, covered by focused tests, lint clean.
- Phase 3: implemented; explicit / `NO_REPO` / free-form / repo-selection-required / `continue_without_repository=True` all covered.
- Phase 4: implemented; missing-field resolver order, finalization-context-once, and `not_actionable` priority skip all covered.
- Phase 5: implemented; artefact shapes, mixed assignee input, and atomicity all covered.
- Phase 6: implemented; explicit ID, generated UUID, duplicate-workflow handling, and primitives-only workflow input all covered.
- Phase 7: implemented — `CookiePoemAgent` example + `run_cookie_poem_agent` management command + expanded base-class docstring.

### Phase 0 — Prerequisite infra fix

Patch `create_task_and_trigger()` in `custom_prompt_internals.py` to forward context fields:

- `sandbox_environment_id=context.sandbox_environment_id`
- `posthog_mcp_scopes=context.posthog_mcp_scopes or "read_only"`

Add a regression test that a `CustomPromptSandboxContext` with those values leads to `Task.create_and_run()` being called with those values.

This fix benefits existing Signals repo selection and report research too.

### Phase 1 — Raw session support and validation retry

Add one of:

- `MultiTurnSession.start_raw()` returning `(session, raw_text)`, or
- a custom-agent session wrapper that uses `create_task_and_trigger()`, `poll_for_turn()`, and `send_followup()` directly.

Implement:

- JSON extraction and Pydantic validation inside custom-agent `send()`.
- Validation-error follow-up prompts.
- Default validation retries of 3.
- Per-call `validation_retries`, including 0.
- Typed validation failure exception.

### Phase 2 — Schemas, loader, base class skeleton

Add:

- `schemas.py`
- `loader.py`
- `base.py`
- `__init__.py`

Implement:

- Identifier validation.
- Importable class-path generation and validation.
- No manual registration.
- Register methods.
- In-memory component state.
- `send()` prompt/schema wrapper with a fake/injected session factory for tests.
- Session cleanup behavior.

No Temporal or persistence yet in this phase.

### Phase 3 — Repository resolution

Add `repo_selection.py`.

Implement:

- `NO_REPO` sentinel.
- Explicit repository normalization.
- Free-form repo selection from `initial_prompt`.
- `PostHog/.github` sandbox fallback for `NO_REPO`.
- Generic team user resolver for no-repo runs.

Unit-test all three repository modes.

### Phase 4 — Default resolvers

Add `default_resolvers.py`.

Implement:

- Prompt builders.
- One-time final report preparation context.
- Default title/description/actionability/priority/assignee resolution.
- Skip priority by default if actionability is `not_actionable`.

Unit-test no-default behavior when all fields are registered and resolver behavior when fields are missing.

### Phase 5 — Direct ready-report persistence

Add `persistence.py`.

Implement:

- Direct creation of `SignalReport(status=READY)`.
- Atomic report, artefact, and task-link persistence.
- No `transition_to()` usage.
- No placeholder/in-progress report creation.

Unit-test API-compatible artefact shapes and atomicity.

### Phase 6 — One generic Temporal wrapper

Add `products/signals/backend/temporal/custom_agent.py` and register it in `products/signals/backend/temporal/__init__.py`.

Implement:

- Workflow input/output dataclasses.
- `CustomSignalAgentWorkflow`.
- `run_custom_signal_agent_activity` with `Heartbeater()`.
- Public `run_agent` / `arun_agent` helpers.
- Workflow ID generation and duplicate handling.
- Activity-side class import and identifier validation.

Use a single activity attempt by default.

### Phase 7 — Documentation and example agent

Add an example custom agent after the base is working.

Example should demonstrate:

- Mandatory identifier.
- Zero manual registration.
- Multiple `send()` calls.
- Validation retry override.
- Manual component registration.
- Missing component default resolution.
- `NO_REPO` usage.
- Explicit repository usage.

## Test plan

### Base/session tests

- First `send()` lazily starts the session.
- First `send()` includes initial prompt, selected repo context, user prompt, and JSON schema.
- Second `send()` uses a follow-up turn.
- `session.end()` is called on success.
- `session.end()` is called when subclass `run()` raises.
- If no `send()` happens, no session is created and no end signal is sent.
- Labels are propagated to session calls.

### Validation retry tests

- Valid JSON matching schema returns on first attempt.
- Invalid JSON triggers validation-error follow-up.
- Valid JSON with schema errors triggers validation-error follow-up.
- Default retry count is 3.
- `validation_retries=0` validates once and raises without follow-up.
- Custom retry count is honored.
- Final raised error includes label, model name, validation error, and last raw text.
- First-turn validation failure can be retried because raw session support exists.

### Class loading tests

- `run_agent()` includes `agent_path` automatically.
- Top-level importable custom agent loads successfully in the activity.
- Nested/local custom agent class is rejected with a clear error.
- Loaded class must subclass `CustomSignalAgent`.
- Loaded class identifier must match workflow input `(product, type)`.
- No manual registry call is required in tests.

### Register/default resolver tests

- Registering all components prevents default resolver prompts.
- Missing title triggers title resolver.
- Missing description triggers description resolver.
- Missing actionability triggers actionability resolver.
- Missing priority triggers priority resolver for actionable reports.
- Priority resolver is skipped for `not_actionable` unless subclass requires it.
- Missing assignees resolves to valid empty list or prompted reviewer output.
- First missing-field resolver includes final report preparation context exactly once.
- Registered fields are not overwritten by defaults.
- Duplicate registration raises unless `overwrite=True` is used.

### Repository tests

- Explicit repository skips repo selection.
- Explicit repository is normalized to lowercase.
- `NO_REPO` maps sandbox repo to `PostHog/.github` and selected repo to `None`.
- `NO_REPO` does not persist `.github` as the selected repository.
- Omitted repository calls free-form repo selection with `initial_prompt`.
- Repo selection result is included in the research context.
- No selected repository creates a final `READY` “Repository selection required” report and does not run subclass `run()` by default.
- No-GitHub team can run with `NO_REPO` using generic user resolution.

### Persistence tests

- Successful run directly creates a `SignalReport(status=READY)` visible in the Code Inbox list.
- No transition helpers are called.
- Title maps to `SignalReport.title`.
- Description maps to `SignalReport.summary`.
- Actionability artefact uses `actionability`, not legacy `choice`.
- Priority artefact uses `priority`.
- Suggested reviewers artefact is valid JSON and uses lowercased GitHub logins.
- Repo selection artefact is written for explicit repo, selected repo, `NO_REPO`, and repo-selection-required cases.
- Failure before final persistence does not write a partial report by default.
- Underlying sandbox task is linked with `SignalReportTask.Relationship.RESEARCH` when a session was started.

### Temporal tests

- `run_agent()` computes workflow IDs with optional ID vs generated UUID.
- Product/type override is mandatory.
- Workflow input contains primitive fields only, not `Team` or class objects.
- Workflow input includes `agent_path`.
- Duplicate optional ID handles `WorkflowAlreadyStartedError` as idempotent/already-running.
- The single custom-agent workflow and activity are exported from `products/signals/backend/temporal/__init__.py`.
- Workflow uses `settings.VIDEO_EXPORT_TASK_QUEUE` like the rest of Signals.

## Key implementation pitfalls to avoid

- Do not pass `NO_REPO` to `Task.repository`; it will fail model validation.
- Do not store `PostHog/.github` as the selected report repository when the caller chose `NO_REPO`.
- Do not use the existing signal-oriented repo selector unchanged for a free-form initial prompt.
- Do not fake `SignalData` for `initial_prompt`; that creates misleading signal semantics.
- Do not let `MultiTurnSession.start()` swallow first-turn validation failures before the custom retry loop can correct them.
- Do not persist malformed `SUGGESTED_REVIEWERS` content; list filters cast it to `jsonb`.
- Do not pass Django model instances or agent classes through Temporal inputs.
- Do not create per-agent workflows; there is one Signals-owned custom-agent workflow.
- Do not require extenders to manually register their classes.
- Do not retry the main custom-agent activity unless task/report creation is made idempotent.
- Do not overwrite manually registered report fields during default resolution.
- Do not forget to end the `MultiTurnSession` in failure paths.
- Do not depend on `CustomPromptSandboxContext.posthog_mcp_scopes` or `sandbox_environment_id` until the passthrough fix lands.
- Do not add a custom metadata artefact type without a migration and serializer/view updates.

## Proposed defaults and future decisions

Default decisions for v1:

- Completed custom-agent reports are directly created as `READY`, even if actionability is `requires_human_input` or `not_actionable`.
- `not_actionable` reports omit priority by default.
- Assignees default to an empty list when not registered/resolved.
- A new report is created for each successful run; updating an existing custom-agent report is out of scope.
- Metadata is logged and included in workflow input/ID, but not persisted until a metadata field or artefact type exists.
- `NO_REPO` means “no selected subject repository” and uses `PostHog/.github` only as the sandbox bootstrap repo.
- No selected repository from automatic repo selection creates a final ready report requiring human repository selection.

Decisions to revisit after v1:

- Whether to add `SignalReport.metadata` for product/type/run metadata.
- Whether custom-agent reports should emit synthetic signals to make source-product filtering work.
- Whether to add `SignalReportTask.Relationship.CUSTOM_AGENT_RESEARCH`.
- Whether to support updating an existing report instead of creating one per run.
- Whether failed custom-agent runs should create `FAILED` reports or stay visible only through task logs.
