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
