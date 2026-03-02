import type { LLMTrace } from '~/queries/schema/schema-general'

import type { EnrichedTraceTreeNode } from './llmAnalyticsTraceDataLogic'

export function hasTraceContent(trace: LLMTrace): boolean {
    return trace.inputState !== undefined || trace.outputState !== undefined
}

export function findNodeByEventId(tree: EnrichedTraceTreeNode[], eventId: string): EnrichedTraceTreeNode | null {
    for (const node of tree) {
        if (node.event.id === eventId) {
            return node
        }

        if (node.children) {
            const found = findNodeByEventId(node.children, eventId)

            if (found) {
                return found
            }
        }
    }

    return null
}
