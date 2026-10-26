# Data suggestions

Suggests workflows built from a project's own events, on the Workflows empty state.

## How it works

Two background jobs do the work: one makes the cards, one builds a draft when someone clicks a card.
Both run as Celery tasks on the long-running queue, because a run can take minutes and must not hold a web request.

```text
page                       API (presentation/views)        Celery task                 Redis
----                       ------------------------        -----------                 -----
generate ----------------> start_data_suggestions -------> run_data_suggestions -----> cards (7 days)
poll current every 2 s --> get_data_suggestions <-------------------------------------- cards

"Create workflow" --------> start_build ------------------> run_build ----------------> draft (1 hour)
poll build every 2 s ----> start_build <-------------------------------------------- draft
save draft through the normal hog flows create endpoint, then open the editor
```

Making the cards (`_suggest` in `service.py`):

1. Count the last 7 days of the project's events in ClickHouse.
2. Drop events a workflow already triggers on.
3. Ask Jev which lifecycle stage each event marks.
4. Rank by stage weight and volume, then ask Claude Sonnet for ideas.
5. Keep the model's first card per stage, up to 3, ordered by stage weight, and cache them per team.

Building a draft (`_plan_and_build` in `service.py`):

1. Claude Opus plans a graph of up to 20 steps from the card, the step catalog, saved email templates and connected channels.
2. The builder turns the plan into a workflow and rejects plans that do not hold up.
   A trigger with more than 50,000 events a week starts on a random sample that brings it down to about that level.
3. The draft is checked the way the caller's own create request checks it.

## Premade ideas

`python manage.py prepare_workflow_ideas --team-ids <id> ...` runs the card run and a build for each card now, then stores each built card as a `WorkflowIdea` row with its workflow in `definition`.
While a project has such ideas waiting, `current` and `generate` return only those cards, read from Postgres, and no run starts.
The consent and privacy checks apply to premade cards too, so a project that loses AI approval stops seeing them.
A build with `save_draft` saves the stored workflow as a draft and marks the idea accepted in one transaction.
A build without `save_draft` returns the stored workflow, checked with the caller's own create rules, and the idea stays offered.
Once every idea is used, the project gets the generated cards again.

Agents use the same endpoints through three MCP tools in `products/workflows/mcp/tools.yaml`: `workflows-data-suggestions-list`, `-get` and `-create`.
The create tool always sends `save_draft`, so the build task saves the draft itself with the editor's draft rules and returns its `workflow_id`.
Blank settings come back as `missing_inputs`, for the agent to ask the user about.

## Files

| File              | What it does                                                                                           |
| ----------------- | ------------------------------------------------------------------------------------------------------ |
| `service.py`      | Runs both jobs: caching, locks, consent checks, and the order of the steps above. Start here.          |
| `premade.py`      | Premade ideas: storing them, their cards, and locking one to save its draft.                           |
| `event_volume.py` | Counts events in ClickHouse. Samples large teams and recounts what the sample missed.                  |
| `stages.py`       | Asks Jev for each event's lifecycle stage, with confidence rules.                                      |
| `ranking.py`      | Stage weights, scoring, and which events reach Jev and Claude.                                         |
| `planner.py`      | The two Claude prompts and the schemas Claude answers in.                                              |
| `llm.py`          | The shared Claude client: strict JSON schema output, free for the customer, reported to LLM analytics. |
| `builder.py`      | Turns a plan into a workflow: graph checks, step configs, waits between emails, copy cleanup.          |
| `email_design.py` | Renders a plain email (heading, paragraphs, unsubscribe link) with an editor design.                   |
| `team_context.py` | What the team already has: used triggers, channels, Slack, email sender, saved templates.              |

Outside this folder:

| File                                              | What it does                                                              |
| ------------------------------------------------- | ------------------------------------------------------------------------- |
| `facade/data_suggestions.py`                      | Connects the service to the Celery tasks.                                 |
| `tasks/data_suggestions.py`                       | The two Celery tasks.                                                     |
| `presentation/views/workflow_data_suggestions.py` | The `current`, `generate` and `build` endpoints, scopes and AI throttles. |
| `presentation/views/data_suggestion_drafts.py`    | The draft check, using the real workflow serializer.                      |
| `services/hog_flow_templates.py`                  | `list_step_templates`, the step catalog the planner may use.              |
| `frontend/setupGuide/suggestions/`                | The cards and the logic that polls and builds.                            |

## Things to know

- One run per team and one build per card and caller run at a time, through token locks in Redis.
  A run only skips writing its result when a newer run holds the lock, because reads can come from a replica.
- Failures show nothing, with no rules-based fallback.
  A failed run is cached as unavailable for 5 minutes, so an outage does not rerun the queries on every visit.
- Only calls that can start model spend count against the user's PostHog AI rate limit.
- No AI data processing consent, privacy mode, or no Jev configured means no cards.
- SMS and push are only offered when a provider is connected.
  Settings the model cannot know, like API keys and URLs, stay blank in the draft.

## Tests

- `test/test_data_suggestions.py`: the pure parts, with no endpoint calls (builder, email rendering, schema, ranking, Jev rules).
- `tests/api/test_workflow_data_suggestions.py`: the endpoints with real ClickHouse events and inline Celery. Jev and Claude are mocked.
- `frontend/setupGuide/suggestions/workflowDataSuggestionsLogic.test.ts`: polling and the build flow.
