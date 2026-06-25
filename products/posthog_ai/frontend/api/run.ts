// Tier 1 — prepackaged run surfaces. `RunViewer` called directly (`<RunViewer .../>`) renders the
// default layout — the common embed for "just show/drive a run" (inbox read-only, tasks live). Its
// `.Root` + slots compose a custom layout instead (Tier 2 territory — see ./primitives). `RunComposer`
// is the standalone composer for a caller that owns its own thread rendering.
//
// Part of the `products/posthog_ai/frontend/api/<module>` public surface — import from here, not from
// deep `../components/*` paths. See ../README.md for the tier model and ../AGENTS.md for the coupling rule.

export { RunViewer } from '../components/RunViewer'
export type { RunViewerRootProps, RunViewerProps } from '../components/RunViewer'
export { RunComposer } from '../components/RunComposer'
export type { RunComposerProps } from '../components/RunComposer'
