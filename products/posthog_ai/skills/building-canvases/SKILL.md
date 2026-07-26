---
name: building-canvases
description: >
  Builds and edits PostHog canvases as arbitrary client-side browser applications. Use when any task needs to create,
  update, validate, or publish a canvas using React, Quill, semantic HTML, browser APIs, WebGL, or Three.js. Covers the
  source-project contract, capability declarations, deterministic builds, conflict-safe publishing, and build checks.
---

# Building canvases

A canvas is a client-side browser application. It can be a document, dashboard, visualization, form, game, WebGL scene,
or another browser experience. Framework choice is an implementation detail, not a user decision.

## Choose an implementation

- Use React and Quill for application state, forms, reusable components, and interfaces that should match PostHog.
- Use semantic HTML, CSS, and direct browser APIs for documents, focused interactions, graphics, and programs where React
  adds no useful structure.
- Mix approaches when useful. React can own the interface around a Three.js scene or another browser API.

Read [React and Quill](references/react-quill.md) when using React or PostHog UI primitives. Read
[HTML and WebGL](references/html-webgl.md) for direct browser applications.

## Work from the current source

1. Resolve or create a desktop file-system dashboard item for the target canvas.
2. Call `posthog:canvas-source-get`. If the canvas has no normalized source yet, convert its legacy single-file React
   source into the standard project shape before publishing the first new version.
3. Keep the returned version ID. It is the base for optimistic concurrency.
4. Edit the complete source project in the task workspace. Do not store generated source in a database field or publish
   only a patch.

Every requested edit belongs to a fresh task run. A run publishes at most one source version. Canvas history remains the
canonical history even when several tasks edit the same canvas.

## Declare capabilities

Generated code has no PostHog credentials. It uses the `ph` runtime bridge and declares every data or side-effect
capability in the source project. Read [Data and capabilities](references/data-and-capabilities.md) before accessing
PostHog data or capturing events. Direct external network access is unavailable
until capability approval exists.

## Validate and publish

Read [Validation and publishing](references/validation-and-publishing.md), then:

1. Call `posthog:canvas-source-validate` until the authoritative build recipe
   succeeds without errors.
2. Call `posthog:canvas-source-publish` with the complete project and the version
   ID read before editing. Sandbox attribution supplies the current task and run
   automatically.
3. If publishing returns `version_conflict`, load the new current source and start a fresh run to reapply the change.
4. Poll `posthog:canvas-build-get` or read `posthog:canvas-history-get` until the cloud build is ready or failed.
5. Treat the cloud build as authoritative. A failed build leaves the previous successful artifact active.

Do not claim completion until the cloud build is ready and the artifact loads without a runtime error.

Hosted functions, secrets, databases, queues, and other server-side micro-app capabilities are not available yet.
