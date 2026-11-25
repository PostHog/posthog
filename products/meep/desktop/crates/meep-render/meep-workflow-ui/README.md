# meep-workflow-ui

Use View’s native workflow inspector and editors in a GPUI application. The UI consumes a workflow definition and a runner trace. The embedding application chooses the runner and owns the catalog.

Create an `Outline` entity with the definition and the latest trace, or JSON null before the first run. Use `receive` for a changed definition or trace, `live` for a running snapshot and `reveal_failure` for a failure deep in a branch. `with_source_icon` and `on_edit` are optional. With `default-features = false`, the package builds the inspector without the native editor or interpreter dependency.

On native targets, `editor::CodeEditor::new` takes a handler, definition, edit target and close callback. It renders View’s visual step form, JSON editor and expression preview. `Request::Save` includes both the expected and proposed definitions. The host commits them together using a compare-and-swap. Return an error to preserve the draft and show the reason. For `Request::Preview`, return the serialized result of `meep_workflows::expressions::evaluate`. Hosts offering the additional script or run targets also implement their corresponding requests.

In an authored view, `meep-render` exposes `WorkflowOutline` and `WorkflowEditor`. [Working gallery](../../../examples/desktop/views/workflows.js)
