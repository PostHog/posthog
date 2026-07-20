// Tier 1 — the embeddable runner scene. `EmbeddedRunner` (`<EmbeddedRunner taskId? />`) is the lazy,
// code-split TaskTracker product (tasks list + composer + agent-run detail) for hosts that want to render
// the whole `/tasks` experience inline — e.g. the Max scene surfacing it behind the sandbox view toggle.
//
// LIGHT boundary: the heavy TaskTracker scene chunk is reached only through `EmbeddedRunner`'s dynamic
// `import()`, so importing this module never statically pulls the scene/list/run-surface into the host
// bundle. Task selection/creation still routes through the scene's own `/tasks/:id` URLs.
//
// Part of the `products/posthog_ai/frontend/api/<module>` public surface — import from here, not from
// deep `../scenes/*` paths. See ../README.md for the tier model and ../AGENTS.md for the coupling rule.

export { EmbeddedRunner, type TaskTrackerProps } from '../components/EmbeddedRunner'

// `SidePanelRunner` (`<SidePanelRunner panelId />`) is the lazy, code-split compact task-run surface
// (composer -> pending thread -> live run, no list/detail chrome) for narrow hosts that render a single
// in-place run rather than the whole `/tasks` list/detail experience — e.g. Max's side panel behind the
// posthog_ai view toggle. Same LIGHT boundary as `EmbeddedRunner`: the heavy chunk is reached only through
// its dynamic `import()`. `panelId` keys an embedded `taskTrackerSceneLogic` instance independent of the
// `/tasks` scene's own singleton — submitting a task here never navigates the host.
export { SidePanelRunner, type SidePanelRunnerProps } from '../components/SidePanelRunner'
