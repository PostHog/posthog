# Generated notebook visualizations

The `GenUI` notebook block turns a prompt into a sandboxed React visualization. Generation is explicit: opening or editing a notebook never starts an AI request.

## Generation path

1. The browser sends a prompt, generation identifier, and the selected model.
2. The backend makes the latest successful result from each SQL or Python cell in the notebook available and rechecks the caller's query and warehouse-source access.
3. The visualization model receives only dataframe names, columns, and types. It never receives row values.
4. The model streams one `src/canvas.tsx` file. Invalid source gets one repair attempt. Canceling closes the model stream before any source is published.
5. The existing Canvas publisher validates, stores, and builds the source.
6. The browser polls Canvas-derived status while the build is active, then loads the signed artifact URL in a script-only sandbox.

There is no GenUI task, snapshot, run history, or persisted lifecycle state. `NotebookGenUI` only associates a notebook node with its Canvas and allowed dataframe names. Existing migration columns from the earlier implementation remain unused for migration compatibility.

The Canvas document root and generated component fill the notebook block's available width and height and respond when the block is resized. Every visualization includes suitable interaction controls, such as camera controls for 3D output or data exploration controls for 2D output. Generation uses explicit visual-quality criteria for composition, recognizable form, and data storytelling. Three-dimensional subjects with visible surface detail use procedural texture maps; self-contained assets prohibit downloads, not textures generated in code.

Blocks offer fast, balanced, and best-quality models. Balanced is the default. The backend accepts only the models shown in the block settings, disables extended reasoning for this single-file generation task, and gives each model a separate output budget and timeout with headroom beyond its expected response time.

## Reading dataframe results

Generated code reads data with a literal call:

```tsx
const frame = await ph.readFrame('weekly_revenue')
```

Canvas already provides a request bridge for `ph.state.get`. The notebook publisher prepends a small source shim that maps `ph.readFrame(name)` onto a reserved state key. The notebook host recognizes only that key prefix and rejects every other Canvas data method.

The frame endpoint checks all of the following on every read:

- the notebook and generated node still exist;
- the dataframe is in the node's allowlist;
- the caller can read queries;
- the caller can still access the warehouse connection used by the resolved run.

Responses use the latest successful cell run and are bounded to 100 columns, 100 rows, 4,096 characters per cell, and roughly 512 KiB in total. Reloading data remounts the artifact and performs fresh reads without another model call.

## Security boundary

Generated source cannot declare network origins, inline queries, captures, or insight access. Canvas validation promotes network use to an error. The artifact CSP disables network connections, and the iframe is sandboxed without same-origin access. Backend authorization remains authoritative even if generated source constructs a reserved state key directly.
