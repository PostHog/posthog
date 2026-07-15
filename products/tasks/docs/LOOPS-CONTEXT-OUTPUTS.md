# Loops and context deliverables: context.md and canvases

A loop attached to a context (a "#channel" / desktop folder) can keep that context's deliverables current on every run: its `context.md`, a canvas and a feed card per run.
Stored on `Loop.context_target` as `{folder_id, name, outputs: {post_to_feed, update_context, canvas_id}}`.
Rationale lives in the Contexts section of [LOOPS.md](./LOOPS.md); this is why and how it works.

## Why it's possible

Nothing a context owns is local to anyone's machine.
Contexts, `context.md` and canvases are all rows on the cloud `desktop_file_system` surface (`/api/projects/:team_id/desktop_file_system/`); the desktop app is just another API client of them.
A sandboxed loop run reaches the same rows through the PostHog MCP `desktop-file-system-*` tools, so it uses the exact write path the app does.

## How it works

All in `products/tasks/backend/logic/services/loop_runs.py`.

**Prompt.** When a write output is on, `render_context_target_block` appends a publish contract to the run's prompt:

- `context.md`: read with `desktop-file-system-instructions-retrieve` (id: folder id), revise, publish the full markdown with `desktop-file-system-instructions-partial-update` (id: folder id, `base_version`: the version just read). Read-modify-write with optimistic concurrency; each publish is a new version. Same contract as the desktop "Build with agent" flow.
- Canvas: publish the complete single-file React source with `desktop-file-system-canvas-partial-update` (id: canvas id). Whole file each time.

**Feed.** `post_to_feed` needs no prompt: the run's `Task` is created with `channel_id` resolved from the context name (`_resolve_feed_channel_id`), so the card appears regardless of what the agent does.

**Scopes.** The tools require `file_system:read`/`file_system:write` (`services/mcp/definitions/core.yaml`). `_augment_scopes_for_context` widens the run's MCP scopes by exactly those two, never to `full`; feed-only grants nothing extra.

**Guardrails.** `folder_id` and `canvas_id` are validated against the team's desktop file system on write; context-attached loops must be `team` visibility; the loop updates an existing canvas, never creates one.

Tests: `tests/test_loop_runs.py` covers which tools and scopes each output combination gets.
Client schema and form: `packages/api-client/src/loops.ts` and `packages/ui/src/features/loops/components/LoopContextFields.tsx` in the PostHog Code repo.
