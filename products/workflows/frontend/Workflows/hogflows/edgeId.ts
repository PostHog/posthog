import type { HogFlowEdge } from './types'

/** One id per edge for both editors, so a + on the tile canvas finds the graph editor's dropzone for the same edge. */
export function getEdgeId(edge: HogFlowEdge): string {
    return `${edge.from}->${edge.to} ${edge.type} ${edge.index ?? ''}`.trim()
}
