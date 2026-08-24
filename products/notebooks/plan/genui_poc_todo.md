# Notebook GenUI proof of concept TODO

Status: proof of concept and notebook-specific hardening implemented; manual acceptance checklist retained below

Branches: `feat/notebook-genui-poc` and `feat/notebook-genui-hardening`

## Current proof of concept

The current branch implements an end-to-end browser path:

- AI notebook instructions can emit `<GenUI prompt="..." />`, while preferring native `Query` visualizations for standard charts.
- The node detects dataframe dependencies from exact names in the prompt, existing serialized inputs, or the closest preceding SQL and Python outputs.
- An editable GenUI node creates or reuses a backing Canvas, queues one source-generation job, polls it to a terminal state, and renders the last published build inline.
- Generated code reads only explicitly declared notebook dataframes with `ph.readFrame(name)`.
- The notebook host serves bounded rows from saved SQL V2 or Python V2 preview results. It sends schemas and preview sizes, but no row values, to the model.
- The artifact runs behind two sandboxed iframe boundaries with network access disabled. The host rejects all data methods except `readFrame` and rejects undeclared frame names.
- The Canvas build platform pins Three.js and its source validator checks declared notebook frame capabilities.
- Regeneration keeps the last successful artifact visible and replaces it only after Canvas publishes a ready build.
- Data refresh is a separate, fast action that reuses generated source and runs automatically after an upstream notebook chain finishes.
- Generated React source is available read-only, and immutable source versions can be selected without invoking the model.

The hardened implementation moves generation coordination into notebook-specific backend services and generated notebook API clients.
It persists a team-scoped GenUI lifecycle row, stores notebook-owned snapshots in object storage, and exposes Canvas only through a narrow backend facade.
The backing Canvas ID and channel stay out of the node's visible controls.

Current data limits are four frames, 100 columns, 100 saved preview rows per frame, 1 MiB per durable snapshot, and 4,096 characters per cell.
The artifact bridge also retains its request concurrency, payload, and timeout bounds.

### Local development

Start the development stack through `./bin/start` so it loads `.env.development`.
GenUI source generation uses the configured AI gateway and does not need a Tasks sandbox or MCP server.
The development environment provides a local-only Canvas artifact signing key so ready builds include iframe artifact URLs.

## Objective

Add a notebook-native `<GenUI />` node that lets PostHog AI generate a custom interactive visualization from a prompt and one or more notebook dataframes.

Treat GenUI as a modern version of a Python plotting cell:

- A Python plotting cell consumes dataframe values and produces a PNG.
- A GenUI cell consumes bounded dataframe snapshots and produces a sandboxed interactive browser artifact.
- Native PostHog visualizations remain the default for ordinary charts.
- GenUI handles visualizations that need arbitrary browser code, such as a spinning 3D globe.

The first proof of concept should validate the product experience and generation quality.
Do not generalize the Canvas data model, extract a new cross-product artifact framework, or reproduce the full Canvas editor inside notebooks.

## Example notebook markup

```jsx
<PythonV2
    nodeId="prepare-locations"
    code="pandas_df = raw_events[['lat', 'lng', 'timestamp']]"
    returnVariable="pandas_df"
/>

<GenUI
    nodeId="location-globe"
    prompt="Render a spinning 3D globe from pandas_df. Plot each location and color it by timestamp."
/>
```

The node detects exact dataframe names in the prompt.
When the prompt does not name one, it keeps valid serialized inputs or uses up to four of the closest preceding named outputs.
Detected names are stored in `inputs` so the runtime allowlist, dependency graph, and staleness controls remain explicit.

The serialized form remains comma-separated for multiple inputs:

```jsx
<GenUI
  nodeId="conversion-map"
  prompt="Compare visits and conversions on an interactive map."
  inputs="visits_df,conversions_df"
/>
```

## Product behavior

- [x] PostHog AI can insert a `<GenUI />` tag while generating or editing a notebook.
- [x] The node starts materializing after insertion without requiring the person to understand Canvas, channels, builds, or source versions.
- [x] The node shows a compact generation state: waiting for inputs, generating, building, ready, or failed.
- [x] A failed generation gives a clear retry action and keeps the last successful artifact when one exists.
- [x] The ready artifact renders inline and follows the notebook node's height and resize behavior.
- [x] The settings view exposes the prompt, detected inputs, separate data refresh and regenerate actions, and does not ask for dataframe names.
- [x] The settings view exposes generated source read-only and keeps Canvas metadata, channel selection, task controls, drafts, publishing controls, and source editing hidden.
- [x] The settings view lists immutable generated versions and can switch the live visualization to an earlier version without invoking the model.
- [x] Editing the prompt creates a new generated source version after an explicit regenerate action.
- [x] Re-running upstream cells marks the GenUI node stale.
- [x] Running a stale GenUI node captures new input snapshots without invoking the model when the input schemas and prompt are unchanged.
- [x] Changing an input schema marks the generated code incompatible and asks for regeneration.
- [x] Reloading the notebook shows the last successful artifact without regenerating it.
- [x] A notebook viewer can render the artifact and its saved input snapshot using normal notebook access checks.

## Proof-of-concept boundaries

### In scope

- The `<GenUI />` notebook tag and node.
- One or more automatically detected SQL V2 or Python V2 dataframe inputs.
- Bounded dataframe snapshots.
- AI-generated HTML, CSS, JavaScript, or React.
- Three.js for 3D visualizations.
- Existing Canvas source validation, build worker, artifact storage, signed URLs, CSP, and sandboxing.
- A small notebook-specific orchestration API.
- A narrow `readFrame` bridge that can read only the node's declared snapshots.
- Prompt editing, regeneration, retry, and last-good rendering.

### Out of scope

- Refactoring Canvas into a generic generated-app platform.
- Making Canvas channels optional or adding notebook fields to Canvas models.
- Sharing the complete Desktop Canvas host with the main frontend.
- Embedding the Canvas source editor or agent conversation in notebooks.
- Live access to arbitrary notebook variables.
- Arbitrary PostHog queries, saved insights, event capture, or external network access from GenUI.
- Arbitrary npm dependencies.
- Streaming data or automatic live updates.
- Large dataframe transport.
- Publishing GenUI artifacts as reusable Canvas documents.
- Building a full GenUI component library.
- Automatically regenerating source whenever upstream data values change.

## Architecture for the proof of concept

```text
PostHog AI inserts <GenUI prompt="..." inputs="pandas_df" />
                              |
                              v
Notebook node calls an idempotent materialization endpoint
                              |
                              v
Backend resolves input schemas and captures bounded snapshots
                              |
                              v
One structured model call receives prompt and schema metadata
                              |
                              v
Backend validates source that calls ph.readFrame("pandas_df")
                              |
                              v
Existing Canvas validation and build pipeline creates an artifact
                              |
                              v
Notebook renders the signed artifact in a sandboxed iframe
                              |
                              v
The host serves only the saved snapshots declared by this GenUI node
```

The implementation uses a normal Canvas as a hidden backing detail.
The notebook backend owns Canvas and generation coordination behind GenUI-specific endpoints.
The frontend knows only about the GenUI node, its consolidated lifecycle status, its signed artifact URL, and its declared snapshots.

Record the backing Canvas limitation in the implementation PR.
A later production design can introduce a generic artifact owner or another storage model if the proof of concept succeeds.

## Persisted GenUI state

- [x] Add a team-scoped notebook model for materialized GenUI nodes.
- [x] Include `team_id` and use the repository's fail-closed team scoping conventions.
- [x] Link the row to the notebook and identify the node with its stable `nodeId`.
- [x] Add a uniqueness constraint for `(team_id, notebook_id, node_id)`.
- [x] Store the normalized prompt and normalized input bindings.
- [x] Store a generation hash derived from the prompt, bindings, input schemas, and generator version.
- [x] Store the backing Canvas ID as a soft UUID reference for the proof of concept.
- [x] Keep the initial nullable task ID column migration-compatible without exposing or using it in generation.
- [x] Store lifecycle status, a typed error code, and a bounded error message.
- [x] Store the current source version and build IDs needed to find the last successful artifact.
- [x] Store snapshot metadata and object-storage references instead of dataframe contents in Postgres.
- [x] Track creation, update, generation, and snapshot timestamps.
- [x] Remove orphaned GenUI state, snapshots, and backing Canvas state when a node or notebook is deleted.

Suggested lifecycle states:

```text
awaiting_inputs
awaiting_generation
generating
building
ready
failed
stale
incompatible
```

Do not store generated source, artifact files, or complete dataframe values in notebook markdown.

## Node contract and notebook integration

- [x] Add `NotebookNodeType.GenUI`.
- [x] Register the `GenUI` markdown tag and insertion command.
- [x] Define attributes with explicit TypeScript return types:
  - `nodeId`: stable and required after insertion.
  - `prompt`: generation instruction.
  - `inputs`: internally serialized, comma-separated dataframe names for the proof of concept.
- [x] Normalize whitespace and reject duplicate or invalid dataframe names.
- [x] Detect exact prompt references or use the closest preceding named outputs when `inputs` is empty.
- [x] Require at least one prompt and allow zero inputs for data-free graphics experiments.
- [x] Add the node to markdown conversion and serialization paths.
- [x] Add the node to the notebook widget catalog if AI generation relies on that catalog.
- [x] Teach the notebook MCP instructions that native `Query` visualizations are preferred for standard charts.
- [x] Teach the notebook MCP instructions to use `<GenUI />` for custom browser visuals.
- [x] Add GenUI nodes to the notebook dependency graph using `inputs` as references.
- [x] Surface missing, never-run, running, failed, and stale upstream cells.
- [x] Do not start generation for a view-only user.

For the proof of concept, an editable browser may call the idempotent materialization endpoint when it sees a new unresolved node.
The endpoint must make concurrent calls safe so two open tabs cannot create duplicate jobs or backing canvases.
Server-side materialization during notebook writes can follow after the experience is proven.

## Input snapshot contract

GenUI should consume a saved, bounded snapshot rather than query a live Python kernel every time the notebook opens.
This matches the Python plotting model: running the cell captures current inputs and creates a durable output.

- [x] Resolve each input name to its producing SQL V2 or Python V2 node.
- [x] Require a successful upstream run before reading a frame.
- [x] Reuse saved notebook preview results without changing their general architecture.
- [x] Copy the bounded GenUI snapshot to notebook-owned object storage so it survives kernel and sandbox shutdown.
- [x] Tie snapshot access to team and notebook authorization.
- [x] Delete or replace old snapshots when a new GenUI run succeeds.
- [x] Keep the previous successful snapshots until the replacement artifact is ready.
- [x] Do not pass complete dataframe values through Temporal activity payloads.
- [x] Do not include dataframe values in the AI generation prompt.
- [x] Give the model only input names, column names, dtypes, row counts, and truncation metadata.

Initial snapshot shape:

```json
{
  "name": "pandas_df",
  "columns": [
    { "name": "lat", "dtype": "float64" },
    { "name": "lng", "dtype": "float64" },
    { "name": "timestamp", "dtype": "datetime64[ns]" }
  ],
  "rows": [[51.5, -0.1, "2026-08-13T10:00:00Z"]],
  "totalRowCount": 12000,
  "includedRowCount": 1,
  "truncated": true,
  "producedAt": "2026-08-13T10:01:00Z"
}
```

Implemented proof-of-concept limits:

- At most four input frames.
- At most 100 columns and 100 saved preview rows per frame.
- At most 1 MiB per durable snapshot.
- At most 4,096 characters per cell.
- A clear `truncated` value when rows are omitted.
- No silent truncation.

Generated source should aggregate, sample, or ask for upstream reduction when an input is too large.

## GenUI runtime API

Add one runtime method for the proof of concept:

```ts
interface GenUIFrameRequest {
  name: string
  offset?: number
  limit?: number
  columns?: string[]
}

interface GenUIFrameResult {
  name: string
  columns: Array<{ name: string; dtype: string }>
  rows: unknown[][]
  totalRowCount: number
  includedRowCount: number
  truncated: boolean
  producedAt: string
}

const points = await ph.readFrame('pandas_df', {
  columns: ['lat', 'lng', 'timestamp'],
  offset: 0,
  limit: 5_000,
})
```

- [x] Add `ph.readFrame` to the generated artifact runtime.
- [x] Add a declared frame capability to the source and build manifest.
- [x] Reject frame names that the GenUI node did not declare in `inputs`.
- [x] Reject attempts to read another notebook's saved results by exposing only the current notebook's declared frames.
- [x] Enforce row, byte, concurrency, and timeout bounds in the trusted host.
- [x] Return typed lifecycle and error states for missing, stale, truncated, and unavailable snapshots.
- [x] Keep `connect-src 'none'` and do not pass an auth token into the artifact.
- [x] Deny `ph.query`, `ph.loadInsight`, capture, and external navigation by default for GenUI.

The POC may implement the method as a small extension to the existing Canvas runtime contract.
Do not refactor every Canvas host or introduce a general data-source protocol in this branch.
If Desktop opens a backing Canvas that requires notebook frames, it may show a clear unsupported-host error.

## Source generation

- [x] Queue one background Celery job without provisioning a Tasks sandbox or general coding agent.
- [x] Request one structured response containing the complete `src/canvas.tsx` source.
- [x] Run at most one repair call when the response or static source validation fails.
- [x] Tell the model that it is producing one embedded notebook visualization, not a standalone dashboard or document.
- [x] Include the prompt, theme expectations, declared input schemas, and the `ph.readFrame` API contract.
- [x] Tell the model not to query PostHog directly.
- [x] Tell the model not to hardcode dataframe values.
- [x] Tell the model to handle empty data and truncation.
- [x] Tell the model to render responsively without assuming a fixed notebook width.
- [x] Tell the model to clean up animation frames, WebGL resources, timers, and event listeners.
- [x] Tell the model to include a useful empty or error state in the artifact.
- [x] Attach disabled PostHog and network capabilities in trusted backend code instead of model output.
- [x] Validate and publish through the Canvas facade, then let the existing Canvas builder create the artifact.
- [x] Keep source generation separate from dataframe reads so customer values do not enter the model prompt.
- [x] Make generation idempotent for one generation hash.
- [x] Keep the previous ready artifact if generation or building fails.
- [x] Poll generation and build completion through the backend service rather than reproducing the full lifecycle in Kea logic.

## Three.js support

- [x] Add a pinned `three` version to `products/canvas/packages/canvas_builder/manifest.json`.
- [x] Add it to `allowedImportSpecifiers`.
- [x] Add it to the builder package dependencies and lockfile.
- [x] Update the Canvas API serializer help text that lists admitted packages.
- [x] Extend the platform contract test that checks Desktop and builder dependency parity.
- [x] Decide whether direct Three.js is sufficient for the proof of concept before adding `@react-three/fiber`.
- [x] Prefer direct Three.js initially to keep the bundle and generation contract smaller.
- [x] Add concise generation guidance for scene setup, resize handling, animation cleanup, and WebGL disposal.
- [x] Verify that a globe artifact fits the current source and artifact size limits.
- [x] Keep external textures blocked.
- [x] Use generated geometry and colors for the first globe example.

Do not add arbitrary dependency installation to generated projects.
Every admitted package must remain platform-pinned and reproducible.

## Backend API shape

Keep the API notebook-oriented.
The frontend should not call Canvas endpoints directly.

Suggested actions:

```text
POST /api/projects/:team_id/notebooks/:short_id/genui/ensure
GET  /api/projects/:team_id/notebooks/:short_id/genui/:node_id
POST /api/projects/:team_id/notebooks/:short_id/genui/:node_id/run
POST /api/projects/:team_id/notebooks/:short_id/genui/:node_id/regenerate
POST /api/projects/:team_id/notebooks/:short_id/genui/:node_id/retry
GET  /api/projects/:team_id/notebooks/:short_id/genui/:node_id/source
GET  /api/projects/:team_id/notebooks/:short_id/genui/:node_id/versions
POST /api/projects/:team_id/notebooks/:short_id/genui/:node_id/versions/restore
```

- [x] Use serializers as the source of truth for request and response types.
- [x] Add schema annotations and `help_text` to every field.
- [x] Generate frontend API types with `hogli build:openapi` after the endpoint shape stabilizes.
- [x] Validate notebook edit access for ensure, run, regenerate, retry, and version selection.
- [x] Validate notebook view access for status, artifact URL, snapshots, generated source, and version history.
- [x] Resolve all GenUI records through both team and notebook scope.
- [x] Rate-limit generation and cap active builds using existing Canvas limits.
- [x] Return one consolidated status response so the node does not coordinate generation and Canvas build APIs itself.

Suggested status response fields:

```text
node_id
status
prompt
inputs
input_schemas
stale
source_version_id
build_id
artifact_url
capabilities
diagnostics
error
updated_at
```

Do not expose channel IDs or require the frontend to understand the backing Canvas.

## Frontend node

- [x] Read `frontend/src/AGENTS.md`, the UI component skill, the Kea logic skill, the disposables skill, and the user-facing copy skill before implementation.
- [x] Keep orchestration in a small keyed Kea logic rather than React effects.
- [x] Use generated API clients and types.
- [x] Render a compact placeholder while generation or building runs.
- [x] Show the last successful artifact while a replacement is in progress.
- [x] Disable generation actions while a request is active.
- [x] Use the existing notebook node resize behavior.
- [x] Create a minimal artifact frame for signed Canvas artifacts.
- [x] Preserve the nested sandbox and `referrerPolicy="no-referrer"` security properties.
- [x] Implement only the bridge messages needed for rendered, runtime error, theme, and `readFrame`.
- [x] Do not port Canvas comments, selection highlights, navigation, capture, insights, queries, source editing, or draft management.
- [x] Close MessagePorts and remove listeners when the node unmounts.
- [x] Stop polling when the node unmounts or reaches a terminal state.
- [x] Add clear states for missing inputs, stale inputs, generation failure, build failure, expired artifact URLs, and runtime errors.

The minimal artifact host will duplicate a small amount of the Desktop host for the proof of concept.
Keep the protocol surface small and put a follow-up extraction decision behind proof-of-concept results.

## Regeneration and staleness rules

Use separate hashes for source generation and input snapshots.

### Regenerate source when

- The prompt changes and the person chooses regenerate.
- Input bindings change.
- Input column names or dtypes change incompatibly.
- The GenUI SDK or generator version changes and migration is requested.

### Reuse source and capture new snapshots when

- Upstream rows change but the declared schemas remain compatible.
- An upstream cell is rerun.
- A person explicitly runs the GenUI node again.

### Do nothing when

- The notebook is reopened.
- Another viewer opens the notebook.
- The artifact URL is refreshed.
- An unrelated notebook cell changes.

- [x] Derive stale state from upstream run IDs and snapshot metadata.
- [x] Run declared upstream dataframe cells in dependency order before generation when their previews are unavailable.
- [x] Never trigger paid generation repeatedly from render or polling.
- [x] Require an explicit retry after terminal generation failures.

## Security and privacy checklist

- [x] Generated code runs only in a sandboxed iframe on the artifact origin.
- [x] The artifact receives no PostHog session cookie, personal API key, or project secret.
- [x] The CSP keeps network access disabled.
- [x] Frame access is allowlisted by the node's declared inputs.
- [x] Snapshot reads require normal team and notebook authorization.
- [x] Snapshot object keys include and validate the team boundary.
- [x] Input values are not sent to the generation model.
- [x] Prompts, diagnostics, logs, and analytics do not include dataframe rows.
- [x] Runtime responses enforce explicit row and byte limits.
- [x] Error messages do not expose object-storage keys or signed URLs.
- [x] Generated external navigation remains blocked for the proof of concept.
- [x] Artifact and snapshot cleanup follows notebook deletion.
- [x] The implementation does not place large data in Temporal inputs or outputs.

## Observability

- [x] Capture GenUI materialization requested, generation completed, build completed, run completed, and render failed events.
- [x] Record outcome, duration, dependency count, input row count bucket, truncation, source size, and artifact size.
- [x] Do not capture prompt text, generated source, dataframe names, column names, or dataframe values.
- [x] Add structured logs with notebook ID, node ID, Canvas ID, build ID, and outcome.
- [x] Add counters for idempotency hits and rejected input reads.

## Tests

Read the repository's test-writing skill before adding or changing tests.

### Backend

- [x] Parsing and normalization of `inputs`.
- [x] Team and notebook scoping for every action.
- [x] Idempotent ensure calls under concurrent requests.
- [x] One backing Canvas and one queued source-generation job per generation hash.
- [x] Missing and failed upstream input handling.
- [x] Preview-frame bounds and explicit truncation.
- [x] Input values excluded from the generation prompt.
- [x] Unknown or undeclared frame reads denied.
- [x] Source reused for compatible new snapshots.
- [x] Source regenerated for prompt or schema changes.
- [x] Last-good artifact retained after generation or build failure.
- [x] Snapshot and GenUI cleanup with notebook deletion.

### Frontend

- [x] Markdown registration and serialization for `<GenUI />`.
- [x] Missing, waiting, generating, building, ready, stale, and failed states.
- [x] No duplicate ensure request across rerenders.
- [x] Buttons disabled while mutations are active.
- [x] MessagePort cleanup on unmount.
- [x] Undeclared frame requests rejected by the host.
- [x] Runtime error and expired artifact URL handling.
- [x] Last-good artifact remains visible during regeneration.
- [x] Generating and building appear as separate progress states without exposing an internal task UI.

### Reviewer acceptance scenarios

The implementation checklist is complete. Reviewers can use these scenarios to exercise generated WebGL output and browser behavior before moving beyond the proof of concept:

- Build a Python dataframe with `lat`, `lng`, and `timestamp` columns through the notebook UI.
- Insert the example `<GenUI />` tag through PostHog AI.
- Generate a spinning globe using Three.js through the direct GenUI generation flow.
- Verify points come from the dataframe snapshot.
- Resize the notebook node and confirm the WebGL scene follows it.
- Switch light and dark themes.
- Reload the notebook and confirm no model call or rebuild occurs.
- Re-run the Python cell with different rows, run GenUI, and confirm source is reused.
- Change a column name and confirm the node requests regeneration.
- Open the notebook as another authorized user and confirm the saved artifact renders.
- Confirm browser network tools show no requests from the inner artifact except its signed artifact files.

## Suggested implementation order

### Milestone 1: Static GenUI without dataframe inputs

- [x] Register `<GenUI />` and render node states.
- [x] Add the team-scoped GenUI materialization model and API.
- [x] Create a hidden backing Canvas and queue direct source generation through the backend.
- [x] Return one consolidated status response.
- [x] Render the signed artifact with a minimal sandbox host.
- [x] Generate and display a data-free animation through the direct GenUI flow.

This proves prompt to code to build to notebook rendering before adding dataframe transport.

### Milestone 2: Bounded dataframe snapshots

- [x] Resolve declared notebook inputs from saved preview results.
- [x] Capture durable bounded snapshots.
- [x] Add `ph.readFrame` and its capability check.
- [x] Serve bounded saved previews through the trusted notebook host.
- [x] Add dependency and staleness behavior.
- [x] Verify source reuse across data-only reruns.

### Milestone 3: Three.js globe

- [x] Add pinned Three.js support.
- [x] Add Three.js generation guidance.
- [x] Generate the globe example from a Python dataframe.
- [x] Fix resize, theme, cleanup, empty-state, and truncation behavior found during manual testing.

### Milestone 4: AI notebook authoring

- [x] Add `<GenUI />` to the notebook AI tool and widget instructions.
- [x] Prefer native visualization nodes for standard charts.
- [x] Use GenUI only for custom visual and interaction requirements.
- [x] Verify that an AI-created notebook reaches a ready artifact without manual Canvas steps.

## Proof-of-concept exit criteria

- [x] PostHog AI can create a notebook containing a valid `<GenUI />` node.
- [x] The node produces a spinning 3D globe from a Python dataframe.
- [x] The model receives schemas but no dataframe values.
- [x] The artifact cannot access undeclared inputs or the network.
- [x] The artifact survives a notebook reload and Python sandbox shutdown.
- [x] A data-only rerun does not regenerate source.
- [x] The notebook frontend contains no Canvas source editor, channel UI, draft UI, or task conversation UI.
- [x] The branch does not carry over `NotebookNodeCanvas` wiring from `feat/notebook-canvas-node`.
- [x] Native PostHog visualization nodes continue to handle ordinary charts.
- [x] The implementation has enough instrumentation to compare generation success, build success, render success, latency, and truncation.

## Follow-up decisions after the proof of concept

Do not solve these in the initial branch.
Record evidence from the proof of concept first.

- Whether to extract Canvas source, build, and artifact ownership into a generic generated-app model.
- Whether to share one artifact host package between Desktop and the main frontend.
- Whether GenUI should use live frame reads, immutable snapshots, or both.
- Whether to support Arrow transfer and larger datasets.
- Whether to add `@react-three/fiber`, D3, map libraries, or other pinned dependencies.
- Whether generated source should be editable in a dedicated GenUI surface.
- Whether GenUI artifacts should be reusable across notebooks.
- Whether server-side notebook writes should materialize GenUI without an open browser.
- Whether successful GenUI patterns should graduate into trusted native visualization components.
