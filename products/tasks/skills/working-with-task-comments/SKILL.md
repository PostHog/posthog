---
name: working-with-task-comments
description: >-
  Read and use comments attached to the current PostHog task, its artifacts, and its canvases. Use
  when the user mentions task comments, artifact or canvas comments, annotations, selected-text
  feedback, replies, unresolved comments, or asks an agent to inspect or act on feedback left in
  PostHog Code. Covers discovering targets, listing and filtering roots, retrieving full threads,
  pagination, anchor/version context, and the task-scoped security boundary.
---

# Working with task comments

Task comments can target the task itself, an artifact, or a canvas. The task-comments tools are
read-only and are available only inside the current PostHog Code task. The host fixes the task; do
not ask for or construct a task id.

## Choose the smallest useful read

- Call `tasks-comments-list` without `artifact_id` to inspect comment roots across the current task.
- Call `tasks-artifacts-list` only when an artifact inventory or an artifact id for filtering is
  useful. It includes artifacts and canvases, including targets that have no comments.
- Pass an `artifact_id` from that inventory to `tasks-comments-list` to restrict the result to one
  artifact or canvas.
- Call `tasks-comments-retrieve` with a root id from the list whenever the root's replies or full
  context matter.

Do not use MCP resource-listing tools to look for comments. Comments are exposed as tools, not MCP
resources.

## Read complete results

Both comment listing and thread retrieval are paginated:

1. Start without a cursor.
2. Process the returned page.
3. Call again with `next` as `cursor` until `next` is null.

When the user asks about all comments, paginate the root list fully. Before acting on a particular
root, retrieve and paginate its complete thread so an earlier reply is not mistaken for the latest
request.

By default, `tasks-comments-list` returns open roots. Set `include_resolved` only when resolved
history is relevant.

## Interpret comment context

Each root identifies its target as a task, artifact, or canvas. Treat the target id returned by the
API as opaque.

- `selected_text` is the quoted text the comment refers to. Use it to locate the intended content;
  do not silently apply the comment to another repeated occurrence.
- Canvas comments may include a saved version. Treat that as historical context for where the
  annotation was made; do not revert the live canvas merely to match it.
- Replies belong to the returned root thread. Read them in sent order and follow the conversation,
  not only the root summary.
- A resolved root is history unless the user explicitly asks to revisit it.

## Common workflows

### Understand comments across the task

1. List all open roots and follow pagination.
2. Group them by returned target when that improves the explanation.
3. Retrieve the full threads relevant to the user's question.
4. Summarize the actual requests and distinguish unresolved work from discussion.

### Work on one artifact or canvas

1. List artifacts when the target id is not already known.
2. Filter the root list with that artifact id.
3. Retrieve every relevant thread completely.
4. Use selected-text and version context while making the requested change.

### Act on feedback

1. Read all relevant open roots and their complete replies before editing.
2. Reconcile comments that overlap or supersede one another.
3. Make and validate the requested changes using the appropriate repository or canvas workflow.
4. Re-list open comments before finishing when the task is long-running or the user may have added
   feedback during the run.

## Boundaries

- These tools cannot create, reply to, resolve, edit, or delete comments.
- Never attempt to select another task: the server rejects cross-task access and the tool schemas
  intentionally expose no task id.
- Do not expose raw anchor metadata or infer private content beyond the normalized fields returned
  by the tools.
- If the tools are unavailable, state that task-comment access is unavailable in the current run;
  do not substitute filesystem searches or comments from another task.
