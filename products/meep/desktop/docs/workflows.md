# Using a workflow as a data source

An agent can deliver a versioned JSON definition alongside a view. The application binds the names in that definition to the capabilities it grants the view. A dashboard, a command-line job and a desktop panel can each host the same recipe.

## Follow one refresh

The gallery recipe asks the logical source `activity` for `recent`. A pure Rhai expression turns the response into rows. A final `dataset.set` replaces the view’s `runs` dataset by ID. The GPUI table reads that dataset directly. Replaying the same input produces the same rows. A failed read or transform leaves the previous rows available because the only dataset write comes last. [Executable recipe](../examples/desktop/views/run-history.json) · [View](../examples/desktop/views/workflows.js)

The same view can run offline or read an isolated PostHog project over HTTP. Both bindings return an array of records with `id`, `status` and nullable `durationMs`. Neither the view nor the recipe changes when the host switches bindings.

```sh
cargo run --locked -p meep-examples -- --open workflows --workflow-backend local
cargo run --locked -p meep-examples -- --open workflows --workflow-backend posthog-fixture
```

To try a definition written by an agent, copy the recipe, edit it and pass its JSON file with `--workflow-file PATH`. The gallery validates it before opening the window. The example table expects a dataset named `runs` with `id`, `shortId`, `outcome` and `duration` fields. Another app supplies its own table schema and source grants. The gallery’s editor saves to its window-scoped catalog. The input file is only read at launch.

## Compose a host

| Piece                     | What the embedding app supplies                                                                                                                                                                                                                                 |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `meep-workflows`          | Validate agent JSON with `Workflow::parse`. Use `runner::run` with a `runner::Host` for headless work. That host supplies sources, optional AI and agent operations, time, state and dataset access. `Run` returns the result and per-step trace.               |
| Mounted workflow catalog  | Give each view its own `ManualCatalog` and delegate its foreground `native.workflows.*` requests. Identical registration is idempotent. Editors can submit an expected definition to detect concurrent changes. The latest invocation owns the displayed trace. |
| `meep-workflow-ui`        | Feed `Outline` a definition and trace. Supply optional source icons and an edit callback. The native `editor::CodeEditor` accepts a definition, an edit target and a request handler for saves, previews and any additional operations the host exposes.        |
| `meep-render`             | Mount the script with its own `ViewHost`. The renderer supplies the mounted runner, the per-view dataset and the native `WorkflowOutline` and `WorkflowEditor` elements. Register and run from an event handler or initialization. Render from local data.      |
| `meep_posthog::workflows` | Bind the deployment, project and flow ID in `BoundWorkflow`. Supply the host’s access token per request. Bind only the operations the particular view may use. The gallery grants the history view a read of recent activity.                                   |

For an LLM-assisted pipeline, use an explicit AI or agent step, persist its output if the run must be reproducible, then pass that output to pure shaping steps. For repeatable projections, put external reads before the transformation and use stable row keys. A multi-step flow may have observable side effects before a later failure. An app that needs an atomic multi-table publish can expose one transactional host operation for the final write.

## Using PostHog behind the view

A PostHog workflow has its own graph, trigger and lifecycle. A portable recipe can call a host binding to start an existing active manual or schedule-triggered flow. The adapter sends the variables with a caller-owned idempotency key and returns a queued receipt. Keep that key with the logical operation and reuse it on retries. An OAuth token belongs to the host.

```rust
let flow = BoundWorkflow::new(origin, project_id, flow_id)?;
let receipt = flow.start(token, operation_key, &variables).await?;
let invocation = flow.status(token, receipt.invocation_id).await?;
```

Status is an independent read. The invocation may take time to appear in PostHog’s results. A view can keep its receipt, refresh later and display the returned status. Application data produced by the remote job needs a named destination, such as a table behind a separate read capability. Invocation metadata alone supplies run history. The gallery exercises the project API through a loopback fixture.

For an offline-first application, persist the last successful projection and its definition revision in the host’s store. Queue a remote dispatch with its idempotency key in the same transaction as the local intent. A background worker can dispatch and reconcile that intent after reconnection. The supplied foreground catalog is in memory. Durable storage, scheduling and reconciliation belong to the host that needs them.
