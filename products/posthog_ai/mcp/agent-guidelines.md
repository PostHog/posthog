# PostHog Agent

PostHog Agent is a PostHog AI agent with access to one PostHog project.
The permissions of this connection limit what it can read and change.
It runs in a cloud sandbox, so it cannot read your local files or uncommitted changes.

## When to use it

Use PostHog Agent for questions and tasks about product data, users, features, experiments, feature flags, errors, session replays, surveys, and dashboards.
It can also plan a feature with evidence from product data.
Do local code edits yourself. Use the answer and the plan from PostHog Agent as input for that work.

## How to use it

1. Call `posthog-agent-run` once for each goal, with a new `client_request_id`.
   Put relevant local information, for example a code excerpt or a diff summary, in `context`.
   Set `repository` and `ref` when the goal needs the code in a GitHub repository.
2. If the response of `posthog-agent-run` is lost, call it again with the same `client_request_id`.
   You then get the same operation, and no second run starts.
3. Call `posthog-agent-status` with the `operation_id`, the `project_id` of the operation, and the last `cursor`.
   Continue until the state is `succeeded`, `failed`, `cancelled`, or `expired`.
   A status request waits up to 50 seconds. That limit applies to one request, not to the task.
   A status timeout does not mean that the task failed. The operation continues.
4. When the state is `needs_input`, show the question to the user.
   Then call `posthog-agent-reply` with the answer of the user and a new `client_request_id`.
   The same operation continues.
5. When the state is `succeeded`, show the answer, the assumptions, and the links to the user.
6. To stop an operation, call `posthog-agent-cancel`.
   Closing the conversation or losing the connection does not cancel an operation.

## Notes

- Each response includes a PostHog URL. The user can open it to see the operation later.
- You can do independent work while an operation runs, if your host permits it.
  If your turn ends, the operation continues. Call `posthog-agent-status` again with the same `operation_id` to get the result.
- To ask a follow-up question in the same PostHog AI conversation, start a new operation and set `posthog_conversation_id` to the conversation id of the earlier operation.
