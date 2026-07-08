# Custom Signal Agent

Reference doc for the `products/signals/backend/custom_agent/` package: a thin abstraction that lets PostHog engineers ship one-off Signals-style agents that produce final READY reports in the Code Inbox without writing Temporal, sandbox, repo-selection, or persistence code.

Status: feature-complete locally. No production pilot yet. No automated tests — the test file was deleted along with the `session_factory` DI seam because it was contorting the public interface; manual testing through the management command is the current bar.

## What this is for

You want to write an LLM-backed agent that:

- Runs against a PostHog team (with or without a target GitHub repository).
- Optionally clones one repo into a sandbox, runs `gh`, SQL, MCP, etc.
- Produces a single final report (title, description, actionability, priority, assignees).
- Surfaces in the Code Inbox as a `SignalReport(status=READY)` with compatible artefacts.
- Optionally auto-starts a draft PR via the shared autonomy / priority logic.

Pick this layer (instead of writing your own Temporal workflow) when you want one shared Temporal workflow + sandbox session lifecycle + persistence to do the boring work.

## Module layout

```text
products/signals/backend/
  custom_agent/
    __init__.py              # public re-exports (includes run_agent / arun_agent)
    base.py                  # CustomSignalAgent base class — Temporal-free SDK
    schemas.py               # workflow IO, identifier validation, assignee schema
    loader.py                # dotted-path import + identity validation for the activity
    persistence.py           # direct READY-report creation + artefacts + task link
    examples/
      cookie_poem_agent.py     # canonical minimal example (NO_REPO, one send())
      cursed_comment_agent.py  # realistic example (repo research + agentic resolvers)
  auto_start.py              # shared with the agentic signals pipeline
  temporal/custom_agent.py   # workflow + activity + run_agent/arun_agent launchers
  management/commands/
    run_custom_agent_example.py # CLI smoke test (--agent cookie_poem|cursed_comment)
```

`base.py` has zero `temporalio` / `posthog.temporal` imports. The agent is a
plain async Python object that you construct, drive via :py:meth:`start`, and
discard. The Temporal workflow + activity + launcher functions in
`temporal/custom_agent.py` are _one_ way to wrap that lifecycle — future
wrappers (in-process runners, Temporal schedules, queue consumers) can live
alongside without touching the SDK.

## Public API

### Subclass contract

A custom agent is a `CustomSignalAgent` subclass that implements two methods:

```python
class MyAgent(CustomSignalAgent):
    @classmethod
    def identifier(cls) -> tuple[str, str]:
        return ("my_product", "my_type")  # both must match [a-z0-9][a-z0-9_-]*

    async def run(self) -> bool:
        result = await self.send("Do the thing.", MyOutputModel)
        self.register_title(result.title)
        self.register_description(result.body)
        self.register_actionability(ActionabilityAssessment(...))
        self.register_priority(PriorityAssessment(...))
        self.register_assignees([CustomAgentAssignee(github_login="oliver")])
        return True  # finalize and persist a trailing report
```

`run()` returns a bool: `True` finalizes a trailing report from the registered components; any falsy value emits no trailing report (use this when all reports were already emitted via `report_and_continue()`, or when the run intentionally produces nothing). `title` and `description` must be registered before any finalization point — they have **no default resolver**. Missing either raises `MissingReportComponentError` before any default-resolver LLM calls run.

The class must live in an importable top-level module (no nested classes, no `__main__`); the Temporal launcher captures the dotted path automatically.

### Starting an agent (Temporal-backed)

```python
from products.signals.backend.temporal.custom_agent import run_agent, arun_agent

handle = run_agent(MyAgent, team, initial_prompt, *, repository=None, id=None, model=None)
# or, in async code:
handle = await arun_agent(MyAgent, team, initial_prompt, *, repository=None, id=None, model=None)
```

Both are fire-and-forget module-level functions defined in `temporal/custom_agent.py`. They are **not** re-exported from `custom_agent/__init__.py` — doing so would create a circular import (the SDK package is Temporal-free; the Temporal wrapper depends on it, not the other way around). Import them from `temporal.custom_agent` directly. They start the shared `signals-custom-agent` Temporal workflow and return a `CustomAgentRunHandle(workflow_id, run_id, started)`. Reusing the same optional `id` while a workflow with that id is still running returns `started=False` instead of erroring; all other identity bits (`product`, `type`, `team_id`) are already known to the caller.

The base class itself does not know about Temporal. Other framework wrappers (in-process runners for tests/scripts, Temporal schedules for periodic runs) can be added next to `run_agent` / `arun_agent` without changing the SDK.

### `send()`

```python
async def send(
    self,
    prompt: str,
    output_model: type[T],            # pydantic BaseModel
    *,
    label: str | None = None,
    validation_retries: int | None = None,
) -> T
```

- First call lazily creates the `MultiTurnSession`. Later calls use `send_followup_raw`.
- Always wraps your prompt with `output_model.model_json_schema()` and "return JSON only".
- The first call also prepends an initial preamble with `initial_prompt`, repo context, and a "untrusted evidence" safety blurb.
- On validation failure, sends the validation error back and asks for a corrected response. Default `validation_retries` is 3 (overridable per call, including `0`). After exhaustion raises `CustomAgentValidationError(label, model_name, error, last_raw_text)`.

### Register functions

Plain setters. No coercion, no normalization, no overwrite guard:

```python
register_title(title: str)             # also enforces max_title_length (hard cap)
register_description(description: str)
register_actionability(ActionabilityAssessment)
register_priority(PriorityAssessment)
register_assignees(list[CustomAgentAssignee])
```

`register_title` enforces `self.max_title_length` (default 255) as a hard cap. `title` and `description` have no default resolver, so they must be registered explicitly before any finalization point.

If you call the same `register_*` twice, the second call silently wins. That's fine; build your `run()` so it doesn't happen accidentally.

### `report_and_continue()`

```python
async def report_and_continue(self) -> PersistedCustomAgentReport
```

Call mid-`run()` to finalize and persist the _current_ report state, then reset the title/description/actionability/priority/assignees so `run()` can produce another report against the same sandbox session and conversation. Requires `title` and `description` already registered — if either is missing, raises `MissingReportComponentError` _before_ any default-resolver LLM calls. Resolves remaining unregistered components (actionability → priority → assignees), persists the report + artefacts + task link, fires autostart when there's a selected repo, then clears the component slots. Repository, `MultiTurnSession`, and run identity stay intact.

Use this when one `run()` should emit multiple independent reports against shared research context (e.g. "audit five different feature flags and file a report for each"). After the last `report_and_continue`, return `False` (or just not `True`) from `run()` so no empty trailing report is attempted.

### Class attributes

- `default_validation_retries = 3`
- `max_title_length = 255`

## Base class layout

`CustomSignalAgent` is organized into six sections, in this order:

1. **Init** — class attributes and `__init__`.
2. **Mandatory overrides** — `identifier`, `run`.
3. **Likely called by subclasses** — `send`, `report_and_continue`, `register_*`.
4. **Likely overridden (prompt customization)** — `repository_request_section`, `resolve_*_prompt` (three of them: actionability/priority/assignees).
5. **Unlikely overridden (default resolver implementations)** — `resolve_actionability`/`priority`/`assignees`.
6. **Internal — do not override** — `start` (framework entry point called by the activity) and the `repository` property, plus all private helpers (`_resolve_repository`, `_resolve_missing_report_components`, `_task`, `_finalize_and_persist_current_report`, `_maybe_autostart`, `_reset_report_components`, `_final_report`, `_build_turn_prompt`, `_initial_session_preamble`, `_build_validation_retry_prompt`, `_send_raw`, `_parse_and_validate`). Identifier validation lives in `schemas.validated_identifier`.

Methods in sections 4 and 5 can be overridden by subclasses to customize behavior; section 6 underscore-prefixed methods are internal-by-convention but callable from overrides if needed.

Notably absent from the class: anything Temporal-aware. `run_agent` / `arun_agent` are module-level functions in `temporal/custom_agent.py`; the workflow-ID and import-path helpers they need live next to them.

## Lifecycle

1. `run_agent(MyAgent, team, ...)` (Temporal launcher in `temporal/custom_agent.py`) validates identifier, verifies the team's organization has approved AI data processing (raises `AIDataProcessingNotApprovedError` otherwise), captures `agent_path` via `_agent_import_path`, computes a workflow ID, starts `signals-custom-agent`, returns a handle.
2. Workflow runs `run_custom_signal_agent_activity` (single attempt, 85-min start-to-close).
3. Activity (thin wrapper):
   1. Imports the agent class from `agent_path`; rejects nested/local classes and class-identity mismatch.
   2. Loads the team (with `organization` joined) and constructs the agent with `team`, `initial_prompt`, `repository`, `model`. User and repository resolution happen inside `agent.start()`.
   3. Calls `agent.start()`, which:
      - Resolves `user_id` via `resolve_user_id_for_team(team_id)` if the caller didn't supply one. This **requires a GitHub integration on the team** and raises otherwise.
      - Calls `self._resolve_repository()` (see "Repository modes" below). Free-form selection that returns no repo raises `CustomAgentRepositorySelectionError` and fails the activity.
      - Calls subclass `run()`.
      - For every `report_and_continue()` and (when `run()` returns `True`) for the trailing finalization: verifies `title`+`description` are registered, resolves the remaining components, persists the report + artefacts + task link, fires autostart.
      - Closes the `MultiTurnSession` in `finally`.
   4. Returns `CustomAgentWorkflowOutput(report_ids=[...], repository=..., task_id=...)`.

The sandbox `Task` only exists if `send()` was called at least once. The `SignalReportTask(RESEARCH)` link only happens when a task exists. Each persisted report links to the same task when there are multiple per run.

## Repository modes

The `repository` argument to `run_agent` has three modes, resolved in `CustomSignalAgent._resolve_repository` (internal, not overridable):

| Caller value     | Sandbox repo                  | Selected report repo                                           |
| ---------------- | ----------------------------- | -------------------------------------------------------------- |
| `"owner/repo"`   | `owner/repo` lowercased       | same                                                           |
| `NO_REPO`        | `None`                        | `None`                                                         |
| `None` (omitted) | result of free-form selection | selected repo, or raises `CustomAgentRepositorySelectionError` |

`_resolve_repository` returns a `RepoSelectionResult` directly and stores it in `self._resolved_repository`. `self.repository` is a `@property` that reads `self._resolved_repository.repository`, so there's a single source of truth after `start()` runs.

Free-form selection (`select_repository_for_prompt`) reuses the existing repo cache (`system.integration_repository_cache`) and the `PostHog/.github` dummy clone for the selection sandbox. It uses `MultiTurnSession.start()` (no validation retry — if the model returns malformed JSON, the activity fails and produces no report).

`NO_REPO` is the right choice when the agent doesn't need a repo at all (analytics-only, MCP-only, generative tasks like the cookie example). Autostart is skipped because there's no repo to open a PR against.

## Send / multi-turn details

- Session backing: `products/tasks/backend/logic/services/custom_prompt_multi_turn_runner.MultiTurnSession`.
- Always uses `posthog_mcp_scopes="read_only"`.
- Sandbox env is `SIGNALS_REPORT_RESEARCH` (TRUSTED network access). Repo-selection runs in `SIGNALS_REPO_DISCOVERY` (CUSTOM, GitHub-only domains).
- `Heartbeater()` keeps the Temporal activity alive while the agent thinks.

The activity uses `RetryPolicy(maximum_attempts=1)` for the whole agent run. Retrying would create duplicate sandbox tasks / sessions; persistence is not idempotent.

## Default resolvers

`title` and `description` have **no** default resolver — they must be registered by `run()` before finalization. Missing either at finalization raises `MissingReportComponentError` _before_ any default-resolver LLM calls.

The remaining components have default resolvers that fire only when not registered. Order: actionability → priority (skipped when `actionability == not_actionable`) → assignees.

Each resolver is a pair on `CustomSignalAgent`:

- `resolve_x_prompt() -> str` — returns the prompt body. Override this to tweak wording without touching the wiring.
- `resolve_x() -> None` — calls `send(...)` with the prompt body and the right output schema, then `register_x(...)`. Override for full control over schema or flow.

Default resolvers send their prompt + schema and nothing else — no per-call report-state preamble. They rely entirely on the in-session conversation history (initial prompt, repo context, all prior turns) for context.

To skip all default resolution, register everything in `run()` (and before each `report_and_continue` call when emitting multiple reports).

## Persistence

`create_custom_agent_ready_report` runs in a single Postgres transaction:

- Creates `SignalReport(status=READY, title=..., summary=description, signal_count=0, total_weight=0.0)`.
- Bulk-creates artefacts:
  - `REPO_SELECTION` (always; shape matches `RepoSelectionResult`)
  - `ACTIONABILITY_JUDGMENT` (always)
  - `PRIORITY_JUDGMENT` (when priority is set)
  - `SUGGESTED_REVIEWERS` (when assignees non-empty; JSON list of assignee dicts with lowercased `github_login`)
- Creates `SignalReportTask(relationship=RESEARCH)` if the agent ran a `MultiTurnSession`.

`SignalReport.transition_to()` is not used. Reports go straight to READY.

## Temporal wiring

- Workflow: `@workflow.defn(name="signals-custom-agent")` `CustomSignalAgentWorkflow`.
- Activity: `run_custom_signal_agent_activity`, registered in `products/signals/backend/temporal/__init__.py`.
- Task queue: `settings.VIDEO_EXPORT_TASK_QUEUE` (shared Signals worker).
- Workflow ID: `signals-custom-agent:{team_id}:{product}:{type}-{run_id}`, where `run_id` is the caller-provided `id` or a UUID.
- Input: `CustomAgentWorkflowInput(team_id, agent_path, product, type, run_id, initial_prompt, repository, model)`.
- Output: `CustomAgentWorkflowOutput(report_ids: list[str], repository, task_id)`.

## Auto-start (shared with the signals pipeline)

`products/signals/backend/auto_start.py::maybe_autostart_implementation_task` is the shared entry point. The custom agent's `_finalize_and_persist_current_report` calls it after persistence (wrapped in try/except so autostart failures don't fail the report). It's skipped entirely when there's no selected repo. Custom-agent assignees are mapped to `ReviewerContent` dicts in the agent's `_maybe_autostart` helper.

Any future fix to the autostart hacks (assignment-by-self-opt-in, GitHub-login → PostHog-user resolution, `interaction_origin="signal_report"` magic string, non-transactional task creation) lands in that one module and benefits both code paths.

## Adding a new agent

1. Define a subclass of `CustomSignalAgent` in an importable top-level module.
2. Implement `identifier()` and `async run()`.
3. Wire a tiny helper that loads the team and calls `run_agent(...)`. See `management/commands/run_custom_agent_example.py`.
4. Optional: register it in the `AGENTS` map in `management/commands/run_custom_agent_example.py` so it's runnable via `--agent <key>`.
   For a realistic example that does real repo research and uses the default resolvers, see `cursed_comment_agent.py`.
5. The Temporal workflow is shared, so no Temporal registration is needed.

## Known limitations and decisions

- **GitHub integration required end-to-end.** `resolve_user_id_for_team` raises when the team has no GitHub integration, including for `NO_REPO` runs. Intentional: custom agents are a PostHog-eng tool right now and every relevant team has a GitHub integration.
- **AI data processing consent required.** `arun_agent` refuses to launch for organizations with `is_ai_data_processing_approved=False`, raising `AIDataProcessingNotApprovedError`. Mirrors the `emit_signal` gate. Checked only at the launcher boundary; not re-checked inside the activity.
- **No validation retry on repo selection.** If the free-form repo selector returns malformed JSON, the activity fails and no report is produced.
- **`SignalReport.metadata` is not persisted.** Product / type / run_id / workflow_id live in workflow input and structured logs only. Filtering Code Inbox by source product for custom-agent reports doesn't work yet. Revisit when needed.
- **No failed-report persistence.** If the agent crashes before final persistence, sandbox logs are the only artefact. Future work if Code Inbox needs failed runs surfaced.
- **No automated test coverage on the custom agent layer.** Manual testing through `run_custom_agent_example` is the bar. Reintroduce only without bringing back the `session_factory` knob.
- **Autostart inherits all the signals autostart caveats.** See `auto_start.py` and the Architecture doc.

## Gotchas

- `repository=NO_REPO` is a sentinel string that must never reach `Task.repository`. `CustomSignalAgent._resolve_repository` translates it; don't hand-roll a different path.
- `agent.task` is `None` until the first `send()`. Skip the task link if it's still `None` at persistence time (the persistence layer already does this).
- The workflow name `"signals-custom-agent"` is referenced by string in `arun_agent` (matching `@workflow.defn(name=...)` on `CustomSignalAgentWorkflow`). Keep them in sync.
- Workflow input must stay primitive/dataclass; never pass `Team` objects, agent classes, or pydantic instances through Temporal.

## Simplification history

Applied cleanups from earlier review passes (kept here for context; nothing pending):

1. ~~**Collapse `ResolvedCustomAgentRepository` into `RepoSelectionResult`.**~~ Done. `_resolve_repository` returns a `RepoSelectionResult` directly; the wrapper dataclass and `RepositoryMode` Literal are gone.
2. ~~**Drop `CustomAgentWorkflowOutput.status`.**~~ Done. Reports always persist as READY; add a status back when there's a non-ready outcome to communicate.
3. ~~**Move `_repository_selection_required_report` onto the agent class.**~~ Done differently: the synthetic "Repository selection required" report is gone; `_resolve_repository` raises `CustomAgentRepositorySelectionError` and the activity fails. Subclasses that want the soft-landing behaviour can override `__init__` to coerce inputs, or override `_resolve_repository` (internal-by-convention, not enforced).
4. ~~**Move `_validated_identifier` to `schemas.py`.**~~ Done. Now a module-level `schemas.validated_identifier(agent_class)` shared by the loader and the Temporal launcher.
5. ~~**Inline `_normalize_repository`.**~~ Done. The five-line normalizer is inline in `_resolve_repository`.
6. ~~**Convert `self.repository` to a `@property`.**~~ Done. Reads from `self._resolved_repository.repository`; no more dual-write smell.

Deliberately kept:

- **`validate_agent_class_identity` defense-in-depth.** The launcher already encodes `(product, type)` in the workflow ID, so a mismatch at start-time is impossible. The activity-side check only catches `identifier()` changing between launch and activity execution on a long-running workflow that survives a deploy. Cheap to keep, hard to debug if dropped silently.

## Open questions / future work

- Whether to add `SignalReport.metadata` (or a `CUSTOM_AGENT_METADATA` artefact) for product/type/run_id.
- Whether custom-agent reports should emit synthetic signals to participate in source-product filters.
- Whether to support updating an existing custom-agent report vs always creating a new one.
- Whether to expose `posthog_mcp_scopes` and sandbox env choice on the public API. Currently locked to `read_only` + `SIGNALS_REPORT_RESEARCH`.
- Whether to add Temporal-schedule and in-process runners next to `arun_agent` / `run_agent` (the base SDK is already Temporal-free in anticipation of this).
