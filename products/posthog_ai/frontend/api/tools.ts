// Tier 4 — tool-renderer extension seam. Isolated in its own module because the registry registers the
// built-in renderers at module load (a top-level side effect that is NOT tree-shaken away) — importing
// it pulls that chunk in. Use ONLY when your product renders its own tool cards (insights, dashboards,
// recordings…): register them from your own scene's entrypoint via `registerToolRenderers`, exactly as
// Max does in scenes/max/messages/adapters/registerMaxToolRenderers. Tools without an adapter fall
// through to the generic MCP card. This is the generic per-product seam — Max is its first consumer,
// not a special case.
//
// Part of the `products/posthog_ai/frontend/api/<module>` public surface — import from here, not from
// deep `../components/tool/*` paths. See ../README.md for the tier model and ../AGENTS.md for the rule.

export { toolRegistry, lookupToolRenderer, registerToolRenderers } from '../components/tool/toolRegistry'
export type { ToolRendererProps, ToolRegistryEntry, ToolRegistry } from '../components/tool/toolRegistry'
export { GenericMcpToolRenderer } from '../components/tool/GenericMcpToolRenderer'
export { DataToolRow } from '../components/tool/DataToolRow'
export { ToolActivity } from '../components/tool/ToolActivity'
export type { ToolActivityProps } from '../components/tool/ToolActivity'
export { FilePath } from '../components/tool/FilePath'
export { findAllDiffContent, getDiffStats, languageFromPath } from '../components/tool/toolDiffContent'
export type { ToolCallDiffContent } from '../components/tool/toolDiffContent'
