// Tier 1 — the `RunSurface` compound (`Root` + the `.Thread/.Composer/.Resources/.ContextUsage` slots) for
// consumers that build a custom run layout: `RunSurface.Root` binds the stream logic and bootstraps the run;
// the slots compose into whatever layout the surface needs (a live composer for tasks; the meta bars for an
// embed). There is no default layout — for the common no-input read-only embed, use `ReadonlyRunSurface`
// (./readableRun) instead.
//
// EAGER, not lazy: this statically pulls the heavy compound (stream logic, virtualized thread, tool/diff
// renderers). Import it only from an already route-split scene (the tasks runner) or another lazily-loaded
// layout module — never from a light bundle that should stay split (use ./readableRun there).
//
// Part of the `products/posthog_ai/frontend/api/<module>` public surface — import from here, not from
// deep `../components/*` paths. See ../README.md for the tier model and ../AGENTS.md for the coupling rule.

export { RunSurface } from '../components/RunSurfaceImpl'
export type { RunSurfaceRootProps } from '../components/RunSurfaceImpl'
