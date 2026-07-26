---
name: validating-and-publishing-canvases
description: >
  Validate and publish a canvas source project safely: the source-project shape, reading the
  current version pointer, iterating on validation diagnostics, guarded publishing with
  expected_current_version_id, and recovering from a 409 version_conflict without overwriting
  concurrent work. Use whenever a canvas edit is ready to save, a canvas publish tool returns
  diagnostics or a conflict, or a task needs to understand canvas version history.
---

# Validating and publishing canvases

A canvas's source lives in PostHog, versioned per publish. Publishing is guarded: every edit is
based on a specific version, and the server refuses to overwrite newer work.

## The source project

`desktop-file-system-canvas-source-retrieve` returns:

- `project` — `schemaVersion` (1), `files` (path → content), `entryHtml` (`"index.html"`),
  `dependencies` (exact platform-pinned versions), `canvasSdkVersion`.
- `current_version_id` — the version your edits are based on. Keep it; the publish needs it.
  It is `null` for a canvas that has never been published — pass that `null` on the first publish.

Until the canvas build service ships, edit only `src/canvas.tsx` (the single mounted React
component) and leave `index.html` and `dependencies` exactly as returned — extra files, new
dependencies, or version drift fail validation.

## Validate until clean

`desktop-file-system-canvas-validate-create` is side-effect free; call it as often as needed.
Diagnostics carry `severity`, a stable `code`, a `message`, and (for file-specific problems)
`path` and `line`:

- `error` diagnostics block publishing — fix all of them. Common ones: `import_not_allowed`
  (only react, react-dom, @posthog/quill, recharts, lucide-react, dayjs are importable),
  `forbidden_dynamic_import` / `forbidden_require` / `forbidden_inline_script`,
  `unsupported_file` (only `index.html` + `src/canvas.tsx` for now), `missing_component`,
  `dependency_not_admitted` / `dependency_version_mismatch`, and path/size violations.
- `warning` diagnostics don't block, but heed them: `network_fetch` / `network_xhr` mean the code
  reaches for the network directly — the sandbox will block it at runtime; use the `ph` bridge.

## Publish guarded

Publish the **complete** project with `desktop-file-system-canvas-publish-create`:

- Always pass `expected_current_version_id` — the `current_version_id` you read (or explicit
  `null` on a first publish). Unguarded publishes can silently clobber concurrent edits.
- Include a short `prompt` describing the change; it becomes the version-history entry's label.
- Pass `name` only to rename the canvas (e.g. a first build of an untitled canvas).
- Publish once per requested change. If the user asks for another edit afterwards, re-read the
  source (the head may have moved) and publish again — don't batch unrelated changes into one
  version, and don't publish work-in-progress after every micro-edit.

The response returns the new `current_version_id`; the canvas app picks the version up
immediately.

## Recovering from 409 version_conflict

A 409 means the canvas moved past your base — a concurrent publish or a user's undo. The response
includes the live `current_version_id`. Never retry unguarded to force your version through:

1. Re-read the source with `desktop-file-system-canvas-source-retrieve`.
2. Re-apply your edits to the fresh source (the new head may contain someone else's changes —
   preserve them).
3. Publish again with the new `current_version_id`.

## Version history semantics

Each publish appends a full snapshot and moves the head pointer; users can undo/redo between
versions in the app. Publishing on top of an undone state discards the redo tail (history stays
linear), which is why the guard matters: basing your publish on the version you actually read is
what keeps a user's undo, another agent's publish, and your edit from silently erasing each other.
