// Tier 2 — React bindings for frontend context injection and tool-stream subscription. Deliberately a
// thin module: it pulls only the two headless logics (`runContextLogic`, `runStreamLogic`) and the pure
// tool-key resolver, so a consumer that only needs to inject context or listen for tool changes doesn't
// drag the markdown/virtualization presenter chunk that `./primitives` carries.
//
// Part of the `products/posthog_ai/frontend/api/<module>` public surface — import from here, not from
// deep `../components/*` paths. See ../README.md for the tier model and ../AGENTS.md for the coupling rule.

// Context injection — register a source of typed context references for the duration a writer is mounted.
export { useAgentContext, AgentContext } from '../components/AgentContext'
export type { UseAgentContextOptions, AgentContextProps } from '../components/AgentContext'

// Tool-stream subscription — react to streamed tool lifecycle for a specific set of tools.
export { useToolStream, ToolStreamListener } from '../components/useToolStream'
export type { UseToolStreamOptions, ToolStreamListenerProps } from '../components/useToolStream'
