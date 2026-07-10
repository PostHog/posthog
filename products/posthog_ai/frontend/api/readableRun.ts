// Tier 1 — prepackaged read-only run surface. `ReadonlyRunSurface` (`<ReadonlyRunSurface .../>`) is the lazy,
// code-split embeddable for "just show a run": it renders the run thread (and, for a live run, the meta bars)
// behind a `RunLogSkeleton` fallback — no composer, no approval prompt. This is the common embed (the inbox
// detail views). It streams fresh frames while running when `interaction='live'`, and replays the snapshot
// once when `interaction='read-only'`.
//
// LIGHT boundary: the heavy `RunSurface` compound is reached only through `ReadonlyRunSurface`'s dynamic
// `import()`, so importing this module never statically pulls the impl/thread/stream logic/tool registry —
// the consumer's bundle stays split. For a custom layout, reach for the eager compound in ./runSurface.
//
// Part of the `products/posthog_ai/frontend/api/<module>` public surface — import from here, not from
// deep `../components/*` paths. See ../README.md for the tier model and ../AGENTS.md for the coupling rule.

export { ReadonlyRunSurface, type ReadonlyRunSurfaceProps } from '../components/ReadonlyRunSurface'
