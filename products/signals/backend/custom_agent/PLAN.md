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
    __init__.py              # public re-exports
    base.py                  # CustomSignalAgent base class
    schemas.py               # workflow IO, identifier validation, assignee schema
    loader.py                # dotted-path import + identity validation for the activity
    persistence.py           # direct READY-report creation + artefacts + task link
    examples/
      cookie_poem_agent.py   # canonical minimal example (NO_REPO, one send())
  auto_start.py              # shared with the agentic signals pipeline
  temporal/custom_agent.py   # signals-custom-agent workflow + activity
  management/commands/
    run_cookie_poem_agent.py # CLI smoke test
```

## Public API

### Subclass contract

A custom agent is a `CustomSignalAgent` subclass that implements two methods:

```python
class MyAgent(CustomSignalAgent):
    @classmethod
    def identifier(cls) -> tuple[str, str]:
        return ("my_product", "my_type")  # both must match [a-z0-9][a-z0-9_-]*

    async def run(self) -> None:
        result = await self.send("Do the thing.", MyOutputModel)
        self.register_title(result.title)
        self.register_description(result.body)
        self.register_actionability(ActionabilityAssessment(...))
        self.register_priority(PriorityAssessment(...))
        self.register_assignees([CustomAgentAssignee(github_login="oliver")])
```

The class must live in an importable top-level module (no nested classes, no `__main__`); `arun_agent` captures the dotted path automatically.

### Starting an agent

```python
MyAgent.run_agent(team, initial_prompt, *, repository=None, id=None, model=None) -> CustomAgentRunHandle
# or
await MyAgent.arun_agent(...)  # same shape
```

Both are fire-and-forget: they start the shared `signals-custom-agent` Temporal workflow and return a `CustomAgentRunHandle(workflow_id, run_id, product, type, team_id, started, already_running)`. Reusing the same optional `id` returns `already_running=True` instead of erroring.

### `send()`

```python
async def send(
    self,
    prompt: str,
    output_model: type[T],            # pydantic BaseModel
    *,
    label: str | None = None,
    include_report_context: bool = True,
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

`register_title` enforces `self.max_title_length` (default 255) as a hard backstop; the soft limit lives in the schema given to the LLM (`_TitleResolution.title` has `max_length=96`). Two limits are intentional — the LLM tends to ignore the soft one.

If you call the same `register_*` twice, the second call silently wins. That's fine; build your `run()` so it doesn't happen accidentally.

### Class attributes

- `default_validation_retries = 3`
- `continue_without_repository = False` — when `True`, free-form repo selection that returns no repo still proceeds with `repository=None`. `NO_REPO` callers don't need this.
- `max_title_length = 255`

## Lifecycle

1. `run_agent` validates identifier, captures `agent_path` via `cls.import_path()`, computes a workflow ID, starts `signals-custom-agent`, returns a handle.
2. Workflow runs `run_custom_signal_agent_activity` (single attempt, 85-min start-to-close).
3. Activity:
   1. Imports the agent class from `agent_path`; rejects nested/local classes and class-identity mismatch.
   2. Resolves the team and a `user_id` via `resolve_user_id_for_team`. This **requires a GitHub integration on the team** and raises otherwise — by design.
   3. Resolves the repository (see "Repository modes" below).
   4. If repo selection found nothing and `continue_without_repository` is `False`, persists a final "Repository selection required" READY report and stops.
   5. Constructs the agent and calls `agent.start()`, which:
      - Calls subclass `run()`.
      - Calls `resolve_missing_report_components()` for any unregistered field.
      - Closes the `MultiTurnSession` in `finally`.
   6. Persists the final report + artefacts + research-task link in one transaction.
   7. Calls `maybe_autostart_implementation_task(...)` when there's a selected repo (skipped for `NO_REPO` and "no selected repo" cases).

The sandbox `Task` only exists if `send()` was called at least once. The `SignalReportTask(RESEARCH)` link only happens when a task exists.

## Repository modes

The `repository` argument to `run_agent` has three modes, resolved in `CustomSignalAgent.resolve_repository` (classmethod, overridable per subclass):

| Caller value     | Mode       | Sandbox repo                  | Selected report repo    |
| ---------------- | ---------- | ----------------------------- | ----------------------- |
| `"owner/repo"`   | `explicit` | `owner/repo` lowercased       | same                    |
| `NO_REPO`        | `no_repo`  | `None`                        | `None`                  |
| `None` (omitted) | `selected` | result of free-form selection | selected repo or `None` |

Free-form selection (`select_repository_for_prompt`) reuses the existing repo cache (`system.integration_repository_cache`) and the `PostHog/.github` dummy clone for the selection sandbox. It uses `MultiTurnSession.start()` (no validation retry — if the model returns malformed JSON, the activity fails and produces no report).

`NO_REPO` is the right choice when the agent doesn't need a repo at all (analytics-only, MCP-only, generative tasks like the cookie example). Autostart is skipped because there's no repo to open a PR against.

## Send / multi-turn details

- Session backing: `products/tasks/backend/services/custom_prompt_multi_turn_runner.MultiTurnSession`.
- Always uses `posthog_mcp_scopes="read_only"`.
- Sandbox env is `SIGNALS_REPORT_RESEARCH` (TRUSTED network access). Repo-selection runs in `SIGNALS_REPO_DISCOVERY` (CUSTOM, GitHub-only domains).
- `Heartbeater()` keeps the Temporal activity alive while the agent thinks.

The activity uses `RetryPolicy(maximum_attempts=1)` for the whole agent run. Retrying would create duplicate sandbox tasks / sessions; persistence is not idempotent.

## Default resolvers

If you skip a `register_*` call, the corresponding `resolve_*` method on the base class fills it in after `run()` returns. Order: title → description → actionability → priority (skipped when `actionability == not_actionable`) → assignees.

Each resolver is a pair on `CustomSignalAgent`:

- `resolve_x_prompt() -> str` — returns the prompt body. Override this to tweak wording without touching the wiring.
- `resolve_x() -> None` — wraps the prompt with finalization + current-report context, calls `send(...)` with the right output schema, and calls `register_x(...)`. Override this for full control over the schema or the resolution flow.

The first resolver invoked prepends a one-time "final report preparation" block via `consume_finalization_context()`. Subsequent resolvers just get the current report context plus their schema-specific prompt.

To skip all default resolution, register everything in `run()`.

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
- Output: `CustomAgentWorkflowOutput(report_id, status, repository, task_id)`.

## Auto-start (shared with the signals pipeline)

`products/signals/backend/auto_start.py::maybe_autostart_implementation_task` is the shared entry point. The custom agent activity calls it after persistence (wrapped in try/except so autostart failures don't fail the report). It's skipped entirely when there's no selected repo. Custom-agent assignees are mapped to `ReviewerContent` dicts at the call site.

Any future fix to the autostart hacks (assignment-by-self-opt-in, GitHub-login → PostHog-user resolution, `interaction_origin="signal_report"` magic string, non-transactional task creation) lands in that one module and benefits both code paths.

## Adding a new agent

1. Define a subclass of `CustomSignalAgent` in an importable top-level module.
2. Implement `identifier()` and `async run()`.
3. Wire a tiny helper that loads the team and calls `run_agent(...)`. See `cookie_poem_agent.run_cookie_poem_agent`.
4. Optional: add a management command wrapping that helper. See `management/commands/run_cookie_poem_agent.py`.
5. The Temporal workflow is shared, so no Temporal registration is needed.

## Known limitations and decisions

- **GitHub integration required end-to-end.** `resolve_user_id_for_team` raises when the team has no GitHub integration, including for `NO_REPO` runs. Intentional: custom agents are a PostHog-eng tool right now and every relevant team has a GitHub integration.
- **No validation retry on repo selection.** If the free-form repo selector returns malformed JSON, the activity fails and no report is produced.
- **`SignalReport.metadata` is not persisted.** Product / type / run_id / workflow_id live in workflow input and structured logs only. Filtering Code Inbox by source product for custom-agent reports doesn't work yet. Revisit when needed.
- **No failed-report persistence.** If the agent crashes before final persistence, sandbox logs are the only artefact. Future work if Code Inbox needs failed runs surfaced.
- **No automated test coverage on the custom agent layer.** Manual testing through `run_cookie_poem_agent` is the bar. Reintroduce only without bringing back the `session_factory` knob.
- **Autostart inherits all the signals autostart caveats.** See `auto_start.py` and the Architecture doc.

## Gotchas

- `repository=NO_REPO` is a sentinel string that must never reach `Task.repository`. `CustomSignalAgent.resolve_repository` translates it; don't hand-roll a different path.
- `agent.task` is `None` until the first `send()`. Skip the task link if it's still `None` at persistence time (the persistence layer already does this).
- The workflow name `"signals-custom-agent"` is referenced by string in `arun_agent` to avoid an import cycle with `temporal/custom_agent.py`. Keep them in sync.
- Workflow input must stay primitive/dataclass; never pass `Team` objects, agent classes, or pydantic instances through Temporal.

## Open questions / future work

- Whether to make `continue_without_repository` per-call (currently a class attribute).
- Whether to add `SignalReport.metadata` (or a `CUSTOM_AGENT_METADATA` artefact) for product/type/run_id.
- Whether custom-agent reports should emit synthetic signals to participate in source-product filters.
- Whether to support updating an existing custom-agent report vs always creating a new one.
- Whether to expose `posthog_mcp_scopes` and sandbox env choice on the public API. Currently locked to `read_only` + `SIGNALS_REPORT_RESEARCH`.
