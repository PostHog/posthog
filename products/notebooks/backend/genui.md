# Generated notebook visualizations

The `GenUI` notebook block turns a prompt into a sandboxed React visualization. Generation is explicit: opening or editing a notebook never starts an AI request.

## Generation path

1. The browser sends a prompt, generation identifier, selected model, and whether this is an initial generation, regeneration, or improvement.
2. The backend makes the latest successful result from each SQL or Python cell in the notebook available and rechecks the caller's query and warehouse-source access.
3. The visualization model receives only dataframe names, columns, and types. It never receives row values.
4. The backend records the active generation identifier and start time so another browser session can show elapsed time, poll status, and cancel the same request.
5. The model streams one `src/canvas.tsx` file. Invalid source gets one repair attempt within the model's shared wall-clock budget. Canceling closes the model stream before any source is published.
6. The existing Canvas publisher validates, stores, and builds the source as a new immutable source version.
7. The browser polls Canvas-derived status while generation or building is active, then loads the signed artifact URL in a script-only sandbox.

`NotebookGenUI` associates a notebook node with its Canvas and allowed dataframe names. Canvas remains the source of truth for source files, parent relationships, builds, and retained artifacts. `NotebookGenUIVersion` adds notebook-specific metadata for each Canvas source version: the entered prompt, complete effective prompt, operation, and model. Existing Canvas versions without this metadata remain available and use their stored Canvas prompts.

## Versioning and editing

After the first successful generation, the block settings show the complete version history instead of the initial prompt field. Selecting a version previews its retained artifact and displays the prompt represented by that version.

While generation is active, the block shows the current phase, model, elapsed time, typical duration, and estimated time remaining. Once the typical model duration is exceeded, the status says how much longer the request has taken while continuing to poll. The preview-building phase is reported separately. Generated results can also be opened with the node's fullscreen action and exited with Esc.

- **Improve** sends the current source, its complete prompt, and one additional change to the model. Unaffected behavior should remain intact. The entered change and combined prompt are stored with the resulting version.
- **Regenerate** starts from the selected version's complete prompt and creates new source from scratch. The prompt can be edited before generation.
- **View or edit source** reads the selected immutable Canvas source. Saving an edit validates and builds a new version and requires a change description.
- **Restore this version** moves the Canvas head to the selected historical source and rebuilds it. It does not delete later versions.

The version list is not artificially truncated. Optimistic concurrency checks prevent an improvement, source edit, or restore from silently overwriting a newer head.

The Canvas document root and generated component fill the notebook block's available width and height and respond when the block is resized. Every visualization includes suitable interaction controls, such as camera controls for 3D output or data exploration controls for 2D output. Generation uses explicit visual-quality criteria for composition, recognizable form, and data storytelling. Three-dimensional subjects with visible surface detail use procedural texture maps; self-contained assets prohibit downloads, not textures generated in code.

Blocks offer fast, balanced, high-quality, and highest-quality models. Balanced is the default. The backend accepts only the models shown in the block settings, disables extended reasoning for this single-file generation task, and gives each model a separate output budget and shared wall-clock deadline with headroom beyond its expected response time. A repair attempt uses only the time remaining in that same budget.

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

Responses use the latest successful cell run and are bounded to 100 columns, 100 rows, 4,096 characters per cell, and roughly 512 KiB in total. Remounting the artifact performs fresh reads without another model call.

## Security boundary

Generated source cannot declare network origins, inline queries, captures, or insight access. Canvas validation promotes network use to an error. The artifact CSP disables network connections, and the iframe is sandboxed without same-origin access. Backend authorization remains authoritative even if generated source constructs a reserved state key directly.
