# Generated notebook visualizations

The `GenUI` notebook block turns a prompt into a sandboxed React visualization. Generation is explicit: opening or editing a notebook never starts an AI request.

## Generation path

1. The browser sends a prompt and up to four dataframe names.
2. The backend resolves the latest successful run for each dataframe and rechecks the caller's query and warehouse-source access.
3. Claude Haiku receives only dataframe names, columns, and types. It never receives row values.
4. The model returns one `src/canvas.tsx` file. Invalid source gets one repair attempt.
5. The existing Canvas publisher validates, stores, and builds the source.
6. The browser polls Canvas-derived status while the build is active, then loads the signed artifact URL in a script-only sandbox.

There is no GenUI task, snapshot, run history, or persisted lifecycle state. `NotebookGenUI` only associates a notebook node with its Canvas and allowed dataframe names. Existing migration columns from the earlier implementation remain unused for migration compatibility.

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
