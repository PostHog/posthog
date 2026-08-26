# Generated notebook widgets

A generated widget is an interactive app embedded in a notebook. A visualization is one kind of widget; games, calculators, simulators, and data explorers use the same system.

## Resource model

- `GeneratedWidget` owns reusable identity, visibility, provenance, and the current immutable version.
- `GeneratedWidgetVersion` owns source-version identity, prompt delta, model, parent, and the dataframe contract used to generate and run that version.
- `NotebookWidgetInstance` places a widget at a notebook node and records whether it is pinned or follows the widget's latest version.
- `GeneratedWidgetGenerationJob` is the durable, idempotent generation lifecycle.
- A Canvas with `source_policy=notebook_widget` stores, validates, builds, and serves source. The ordinary Canvas API cannot edit or publish it.

The resource is independent of notebook placement. That allows a later picker to copy or link one widget into multiple notebooks without sharing source-notebook data.

## Generation

1. The request snapshots the notebook's current dataframe catalog and bounded context, saves a durable generation job, and returns `202 Accepted`.
2. A Celery worker uses that recorded context to call the selected model.
3. Improvement is based on one immutable parent. Publication fails if the Canvas head moved.
4. Canvas publication, widget-version metadata, instance selection, and terminal job state commit together.
5. Compact status polling reports queued, generating, and publishing phases. Version history loads through a separate paginated endpoint.
6. Stale jobs become terminal failures, and cancellation is shared across authorized editors rather than bound to the initiating browser.

Generation is explicit. Loading a notebook, changing instructions, or retrying a failed status request never starts model work.

## Data contracts

Generation can see every current SQL and Python dataframe name plus bounded schema context. It does not place dataframe rows in the model prompt.

Each successful widget version stores logical frame slots, source run provenance, schema metadata, and a schema hash. Runtime reads:

- resolve against the selected version's contract;
- permit compatible live refreshes and report schema drift explicitly;
- page up to 500 rows per call, with `offset` and `nextOffset`;
- serialize integers outside JavaScript's safe range as decimal strings;
- enforce row and byte budgets on every call.

Generated source reads data with `await ph.readFrame("frame_name", { offset, limit })`.

## Versioning

Initial generation and regeneration record complete instructions. Improve and manual source editing append prompt deltas. Effective instructions are materialized from bounded ancestry only when needed.

Restoring an older state creates a new revert version. It does not move the head pointer backward, so collaborative history remains chronological.

## Runtime boundary

Notebook artifacts run in a script-only iframe with no network origins. A trusted Canvas bootstrap installs the one dataframe MessagePort before generated code runs. The host accepts only that first port and closes it if the document navigates. Notebook source validation also rejects navigation and window-opening sinks.

Notebook-managed canvases cannot be retrieved or republished through ordinary Canvas endpoints.

## Reuse

The Notebooks scene lists generated widgets, their owner, visibility, version count, usage count, and update time.

The future insertion picker should default to **copy**, creating a new widget identity with `forked_from_version_id` provenance. **Link** should remain explicit, default to a pinned version, and ask whether an improvement updates the shared resource or forks it. A linked instance must bind logical inputs to frames in its destination notebook and always resolve data with the current viewer's permissions.
