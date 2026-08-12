# Canvas (BlueBird) dataframe passthrough — analysis

Status: **analysis only, nothing implemented.**
The question: Python/SQL notebook cells produce dataframes; the BlueBird canvas node should be able to query or read them directly.
Is it better to do all analysis outside the canvas and feed it a data source, or to let the canvas pull data by querying for things itself?

## TL;DR

The dichotomy mostly dissolves on inspection.
The notebook already has a first-class data-passing primitive (`returnVariable` → the refs/inputs graph),
and BlueBird already has a pull-based, capability-gated data bridge (`ph.query` / `ph.loadInsight`).
The natural design: **make named dataframes a third capability the canvas can declare and pull, and make the BlueBird node a dependent cell in the notebook's dependency graph.**
The canvas still pulls — but only from frames the notebook produced and the manifest names.
Who does the analysis then stops being an architectural question and becomes a per-notebook choice:
heavy reduction in Python/SQL cells, presentation-level queries in the canvas.

The one genuinely hard fork is **transport for Python-made frames** (live kernel vs durable snapshot),
and there [`sql_v2_frame_store.md`](./sql_v2_frame_store.md) already argued the answer:
durable object handoff beats live coupling, because the sandbox is the most ephemeral component in the system.

## What exists today

### The notebook side (mostly behind `revamped-py-notebooks`)

- Python/SQL V2 cells run in a per-user, per-notebook sandbox (Docker/Modal) with one shared ipykernel and one persistent DuckDB connection.
  Nothing runs in the browser.
  See [`sql_v2_kernel_architecture.md`](./sql_v2_kernel_architecture.md).
- Every cell exports at most one frame under `returnVariable`.
  References are collected client-side (`collectSqlV2Refs` in `notebookNodeSQLV2Logic.ts`), resolved server-side, and routed by engine ([`sql_v2_references.py`](./sql_v2_references.py)):
  a SQL cell is a _query definition_ — referencing it re-inlines it as a CTE and recomputes in ClickHouse, no sandbox needed;
  a Python frame lives only in the kernel, and anything reading it routes into sandbox DuckDB.
- Results live in three tiers:
  1. a bounded envelope (50-row preview, columns/dtypes, media) persisted in the doc and `NotebookNodeRun.envelope`;
  2. a pageable full frame as an Arrow file in the sandbox (`/data/results/<result_id>.arrow`, dies with the sandbox);
  3. behind `notebooks-frame-store`, full frames as Arrow IPC objects in object storage with presigned-URL reads and a ~24h lifecycle ([`sql_v2_frame_store.md`](./sql_v2_frame_store.md)).
- The dependency graph and staleness are modeled both client-side (`buildNotebookDependencyGraph` in `notebookNodeContent.ts`) and server-side ([`sql_v2_state.py`](./sql_v2_state.py), serving `GET sql_v2/state` for agents).

### The BlueBird side

- A canvas is a channel-scoped entity built by an agent task; the published build runs untrusted code in a null-origin sandboxed iframe.
  The CSP is `default-src 'none'` — the iframe cannot fetch anything; every byte enters through the MessagePort bridge
  (`frontend/src/scenes/notebooks/Nodes/NotebookNodeCanvas/canvasArtifactBridge.ts`).
- The bridge exposes exactly three methods, each gated by a capability manifest **frozen into the build**
  (`inlineQueries`, `insights: [shortId]`, `captureEvents`), with widening detection on publish (`products/canvas/backend/capabilities.py`).
  Bounds: 1,000 rows / 2 MB per response, 64 KB requests, 8 concurrent, 30 s timeout (`canvasDataRequest.ts`, `canvasArtifactBridge.ts`).
- The protocol is deliberately kept in sync with the desktop host (`products/desktop/packages/core/src/canvas/freeformSchemas.ts`),
  whose schema already reserves a `run` method for "Phase 3 named queries" — frozen, parameterized queries in published canvases.
  That reservation is philosophically the same thing as a named-frame read:
  a published artifact reading data through a _named, pre-declared_ channel rather than arbitrary inline SQL.
- The canvas node sits entirely outside the notebook graph today:
  attrs are `{id, channelId, prompt}`, no refs, no result, no staleness participation.

## Reframing the question

"Analysis outside, feed a data source" and "BlueBird queries itself" are not competing architectures —
they are the two ends of one contract, and the contract is **what the canvas is allowed to name**:

- Today it can name _ClickHouse_ (inline HogQL) and _insights_ (short IDs).
  So all analysis must be expressible in HogQL or already saved — Python work is invisible to it.
- The missing capability is naming _notebook frames_.
  Once a canvas can declare `frames: ["retention_cohorts"]` and call `ph.readFrame("retention_cohorts", {offset, limit})`,
  the split of labor becomes fluid:
  pandas-heavy work stays in Python cells, last-mile slicing can happen in the canvas, and pure-CH dashboards keep using `ph.query` as they do now.

This also answers the "custom data types" half of the question:
the type that matters is a **typed, paged frame** — `{columns, dtypes, rows, totalRowCount, producedAt, stale?}` —
which the kernel envelope already computes today.
Scalars/params and media are worth keeping out of scope initially; a one-row frame covers most scalar needs.

## Options

### A. Live pull from the kernel

A new bridge method resolves a frame name via the graph and reads Python frames by slicing the sandbox's Arrow result file (the `/page` path).

- Freshest possible data, no new storage.
- Inherits the sandbox's lifetime: a teammate opening the notebook next week gets a canvas that errors until someone re-runs the Python cells.
  Kernels are per-user, so even the same notebook under a different viewer has no frame.
- Tangles with the notebook-wide operation lock (`notebookOperationsLogic`),
  and pages of kernel-run results currently route through a per-user page lock holding a web worker.
- As the _only_ mechanism, this makes canvases feel broken by default.

### B. Durable snapshot handoff

When a run completes, its output frame (already written as `/data/results/<result_id>.arrow`) is also persisted through the frame-store machinery.
The notebook host resolves `readFrame` to the latest completed run's object, fetches the presigned Arrow (host-side — the iframe can't), and serves bounded pages over the bridge.

- Survives sandbox death; works for shared/later-opened notebooks; decouples producer and consumer lifetimes —
  exactly the axes the frame-store doc used to reject live push.
- Costs a retention decision:
  the current 24h lifecycle TTL on `notebooks/frames/` is wrong for "the canvas reads this next month" —
  result snapshots need notebook-lifetime retention with delete-on-supersede, or re-materialization on miss.
- Costs an explicit staleness signal: the graph already derives it; the canvas should render it, not hide it.

### C. Promote frames to warehouse tables

A "publish as dataset" affordance: materialize the frame Delta/Parquet-style (the data-modeling path) so HogQL can query it as a table.

- BlueBird then needs _zero_ new bridge surface — `ph.query('select * from retention_cohorts')` just works,
  and so do insights, other notebooks, and Max.
- The most composable end state but the heaviest:
  team-visible side effects from a notebook cell, naming/lifecycle governance, and a slow iteration loop.
- Wrong as the default path, right as an opt-in "graduate this dataframe" action later.

### D. Bake the query at generation time

Since SQL frames are query definitions, the canvas-generation prompt could hand the agent the CTE-resolved HogQL of named frames, and the canvas bakes it in as an inline query.

- Works today with no protocol change — worth doing regardless as prompt plumbing.
- Only covers SQL frames, silently drifts when upstream cells are edited, and does nothing for Python.

## Recommended shape

### 1. Contract first: the canvas becomes a graph participant

Give the BlueBird node a `uses`-style refs attribute (or derive it from the manifest),
so `buildNotebookDependencyGraph` and `sql_v2_state` see it as a dependent cell.
Staleness badges, chain-runs ("re-run upstream then refresh canvas"), and agent visibility all fall out for free.

The canvas entity is channel-scoped and reusable across notebooks while frame names are notebook-scoped —
so the manifest should declare frame names as _requirements the embedding host must satisfy_, resolved against whatever notebook embeds it.
A canvas dropped into a notebook lacking `retention_cohorts` gets a clear "this canvas needs a frame named X" state.

### 2. One new bridge method, two lanes behind it

`ph.readFrame(name, {offset, limit})`, gated by a new `frames: string[]` manifest capability —
which slots straight into the existing widening-detection model, and rhymes with the desktop's reserved named-queries direction
(design the payload so the desktop host can adopt it).

- **`hogql` frames**: the host resolves the reference exactly as run dispatch does (CTE-inline the definition) and executes via the existing cached query API.
  Fresh, no kernel, no new storage — this lane is nearly free and could ship alone as a first slice.
- **`local` (Python/DuckDB) frames**: serve from a durable result snapshot (option B),
  falling back to the live kernel's `result_id` page path when the sandbox happens to be alive.
  The write side is a small extension of the run callback plus the shipped phase-1 frame store;
  the main new backend surface is a "latest completed run's frame for (notebook, frame name)" read endpoint that presigns for the host.

Keep the existing per-page bounds (1k rows / 2 MB) and return `totalRowCount` + dtypes so the canvas pages honestly.
The architecture's existing trade-off applies unchanged:
heavy reduction belongs upstream in HogQL/DuckDB/pandas; the bridge is for presentation-sized data.

### 3. Feed the agent

At generation time, include the notebook's cell state (frame names, dtypes, row counts, preview — all already in envelopes and `sql_v2/state`) in the canvas prompt,
and have the authoring skill declare the frames it reads in the manifest.
Without this, the passthrough exists but the agent won't use it.

### 4. Later, optionally

"Publish as dataset" (option C) as the graduation path for frames that outgrow one notebook.

## Open questions to decide early

- **Retention/consent for snapshots.**
  Persisting full Python-cell outputs durably is a data-retention change (today they live ≤ sandbox lifetime).
  Bound snapshot size (the 8 MB envelope cap is precedent; snapshots could take a larger but still explicit cap, with `truncated` marked)
  and decide TTL semantics separately from the materialization cache.
- **Freshness semantics.**
  `readFrame` on a stale frame should say so, not silently serve old rows —
  the graph already knows; the response envelope should carry it, and the node UI can offer "re-run upstream".
- **Whose data access.**
  The existing "Run canvas" approval gate covers the viewer-session concern,
  but frame snapshots were produced by _the runner's_ access, and HogQL-lane reads execute under _the viewer's_ access.
  That asymmetry (a viewer could see snapshot rows they couldn't query themselves) needs an explicit stance —
  simplest is to scope snapshot reads to notebook access, which is how notebook previews already behave.

## Bottom line

Don't make BlueBird the analysis engine, and don't make it a passive chart of pre-baked JSON.
Make named frames the interface between the two:
ship the SQL lane first because it's nearly free,
and let the frame-store snapshot lane make Python frames durable enough for canvases to be trustworthy in shared notebooks.
