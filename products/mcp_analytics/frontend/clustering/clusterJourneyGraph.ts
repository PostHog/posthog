import type { SankeyLinkInput, SankeyNodeInput } from '@posthog/quill-charts'

import type { MCPIntentClusterJourneyPathApi } from '../generated/api.schemas'

export const JOURNEY_COLUMN_LABELS = ['Init', '1st tool', '2nd tool', '3rd tool', '4th tool', 'Outcome']
export const ENDED_LABEL = 'Ended'

export type JourneyNodeKind = 'init' | 'tool' | 'ended' | 'completed' | 'error'
export type JourneyOutcome = 'completed' | 'error'

export interface JourneyNodeMeta {
    kind: JourneyNodeKind
}

export interface JourneyLinkMeta {
    outcome: JourneyOutcome
}

export interface JourneyGraph {
    nodes: SankeyNodeInput<JourneyNodeMeta>[]
    links: SankeyLinkInput<JourneyLinkMeta>[]
}

function outcomeOf(path: MCPIntentClusterJourneyPathApi): JourneyOutcome {
    return path.outcome === 'error' ? 'error' : 'completed'
}

/**
 * Turns the top paths of a cluster into a stage-per-column flow graph. Every path spans the same
 * number of columns: Init, one column per step (a step that never happened is `Ended`), then the
 * outcome. Node ids carry the column so the same tool at two stages is two nodes, and links are
 * split by outcome so error flows keep their own ribbon.
 */
export function buildJourneyGraph(paths: readonly MCPIntentClusterJourneyPathApi[]): JourneyGraph {
    const nodes = new Map<string, SankeyNodeInput<JourneyNodeMeta>>()
    const links = new Map<string, SankeyLinkInput<JourneyLinkMeta>>()

    const nodeId = (column: number, label: string, kind: JourneyNodeKind): string => {
        const id = `${column}::${label}`
        if (!nodes.has(id)) {
            nodes.set(id, { id, label, meta: { kind } })
        }
        return id
    }

    for (const path of paths) {
        const outcome = outcomeOf(path)
        const stages: { label: string; kind: JourneyNodeKind }[] = [{ label: 'Init', kind: 'init' }]
        for (const step of path.steps) {
            stages.push(step === null ? { label: ENDED_LABEL, kind: 'ended' } : { label: step, kind: 'tool' })
        }
        stages.push(outcome === 'error' ? { label: 'Error', kind: 'error' } : { label: 'Completed', kind: 'completed' })

        for (let column = 0; column < stages.length - 1; column++) {
            const source = nodeId(column, stages[column].label, stages[column].kind)
            const target = nodeId(column + 1, stages[column + 1].label, stages[column + 1].kind)
            const key = `${source}->${target}::${outcome}`
            const existing = links.get(key)
            if (existing) {
                existing.value += path.count
            } else {
                links.set(key, { source, target, value: path.count, meta: { outcome } })
            }
        }
    }

    return { nodes: Array.from(nodes.values()), links: Array.from(links.values()) }
}

export function describeJourneyPath(path: MCPIntentClusterJourneyPathApi): string {
    const labels = path.steps.map((step) => step ?? ENDED_LABEL)
    return labels.filter((label, idx) => label !== ENDED_LABEL || idx === labels.indexOf(ENDED_LABEL)).join(' → ')
}
