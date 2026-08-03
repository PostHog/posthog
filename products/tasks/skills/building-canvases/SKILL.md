---
name: building-canvases
description: >
  Create or edit a PostHog canvas — a sandboxed browser application (data board, document, form,
  small tool, graphics experiment) stored in PostHog and rendered by the desktop/web app. Use when
  a task asks to build, generate, update, or fix a canvas, or when a canvas id is given as the
  publish target. Covers resolving or creating the target canvas, choosing an implementation
  approach (React + Quill vs plain HTML/browser APIs), the read → edit → validate → publish loop,
  and which companion canvas skills to load for the details.
---

# Building canvases

A canvas is a client-side browser application that runs in a sandboxed iframe inside PostHog.
Its source lives in PostHog — not in a repository — and you read and write it through the
`desktop-file-system-canvas-*` tools. Never write a canvas to a local file; publishing through
the tool is what saves it.

## Resolve the target canvas

- If the task names a canvas id (canvas-initiated tasks do), that is the target. Do not create another.
- Otherwise list candidates with `desktop-file-system-canvases-list` (scope with `channel_id` when the
  request names a channel) and pick the canvas the request refers to.
- Only when no existing canvas is the intended target, create one with `desktop-file-system-canvases-create`
  in the right channel. When you only have a channel name, resolve its id first with
  `desktop-file-system-list` (channels are the `folder` entries).

## Choose the least complex implementation that meets the request

- **React + Quill** — PostHog data products, dashboards, forms, application-like state, and anything
  that should look native to PostHog. Load the `building-react-quill-canvases` skill.
- **Semantic HTML, CSS, and direct browser APIs** — static documents, focused experiments, generative
  graphics, `<canvas>`/WebGL work where React adds no structure. Load the `building-html-canvases` skill.
- **Mix them** when appropriate: React can own the application chrome while Three-style code owns a
  canvas element, or a mostly static page can mount one interactive island.

This is a judgment call, not a persisted mode — ask the user only when the choice changes a
user-visible requirement you cannot infer.

## The iteration loop

1. Read the current source and version pointer with `desktop-file-system-canvas-source-retrieve`.
   Remember `current_version_id` — your publish must be guarded on it.
2. Edit the project files. For any PostHog data the canvas shows, follow the `querying-canvas-data`
   skill (saved insights loaded via the `ph` SDK — never fetch or your own PostHog client).
3. Validate with `desktop-file-system-canvas-validate-create` as often as needed and fix every
   error-severity diagnostic.
4. Publish the complete project with `desktop-file-system-canvas-publish-create`, passing
   `expected_current_version_id`. Follow the `validating-and-publishing-canvases` skill for
   diagnostics and conflict recovery.

Publish once per requested change, when the canvas is ready — not after every micro-edit.

## Source-project shape

- Keep `index.html` as the entry shell returned by the source tool.
- `src/canvas.tsx` remains the conventional React entry component, but it may import additional
  relative TypeScript, TSX, JavaScript, JSON, SVG, CSS, and admitted asset files from the project.
- Self-contained module workers may be imported with `./worker.ts?worker`. A worker must not import
  another local module.
- Binary assets belong in the project's `assets` map as base64 content with an admitted content type.
  PNG, JPEG, GIF, WebP, AVIF, WOFF/WOFF2, WebAssembly, and generic octet-stream assets are supported.
- Keep the platform dependency map exactly as returned. Do not add npm packages; local relative
  imports are project files, while bare imports remain limited to the platform-pinned set.
