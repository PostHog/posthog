// Tier 1 — prepackaged run surfaces. `RunViewer` (`<RunViewer .../>`) is the lazy, code-split embeddable:
// it binds the stream logic and renders the default layout behind a `RunLogSkeleton` fallback — the common
// embed for "just show/drive a run" (inbox read-only, tasks live), and the only form any consumer uses.
// `RunComposer` is the standalone composer for a caller that owns its own thread rendering.
//
// Part of the `products/posthog_ai/frontend/api/<module>` public surface — import from here, not from
// deep `../components/*` paths. See ../README.md for the tier model and ../AGENTS.md for the coupling rule.

export { RunViewer } from '../components/RunViewer'
export type { RunViewerProps } from '../components/RunViewer'
export { RunComposer } from '../components/RunComposer'
export type { RunComposerProps } from '../components/RunComposer'
