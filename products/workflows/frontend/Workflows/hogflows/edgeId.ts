import type { HogFlowEdge } from './types'

/** One id per workflow edge, so every editor surface that draws an edge names it the same way. */
export function getEdgeId(edge: HogFlowEdge): string {
    return `${edge.from}->${edge.to} ${edge.type} ${edge.index ?? ''}`.trim()
}
