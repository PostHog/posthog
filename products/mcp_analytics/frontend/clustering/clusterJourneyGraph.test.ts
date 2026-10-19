import type { MCPIntentClusterJourneyPathApi } from '../generated/api.schemas'
import { buildJourneyGraph, describeJourneyPath } from './clusterJourneyGraph'

const PATHS: MCPIntentClusterJourneyPathApi[] = [
    { steps: ['schema', 'sql', null], outcome: 'completed', count: 20 },
    { steps: ['schema', 'sql', null], outcome: 'error', count: 5 },
    { steps: ['sql', null, null], outcome: 'error', count: 3 },
]

describe('buildJourneyGraph', () => {
    it('keeps one node per stage and one link per outcome between the same nodes', () => {
        const graph = buildJourneyGraph(PATHS)
        // The same tool at two stages is two nodes; Ended repeats per column it fills.
        expect(graph.nodes.map((n) => n.id)).toEqual([
            '0::init::Init',
            '1::tool::schema',
            '2::tool::sql',
            '3::ended::Ended',
            '4::completed::Completed',
            '4::error::Error',
            '1::tool::sql',
            '2::ended::Ended',
        ])
        const schemaToSql = graph.links.filter((l) => l.source === '1::tool::schema' && l.target === '2::tool::sql')
        expect(schemaToSql.map((l) => [l.meta?.outcome, l.value])).toEqual([
            ['completed', 20],
            ['error', 5],
        ])
        const intoError = graph.links.filter((l) => l.target === '4::error::Error')
        expect(intoError.reduce((sum, l) => sum + l.value, 0)).toBe(8)
    })

    it('keeps a tool named Ended separate from a missing step', () => {
        const graph = buildJourneyGraph([
            { steps: ['Ended', null], outcome: 'completed', count: 2 },
            { steps: [null, null], outcome: 'completed', count: 3 },
        ])

        const firstStage = graph.nodes.filter((node) => node.label === 'Ended' && node.id.startsWith('1::'))
        expect(firstStage.map((node) => [node.meta?.kind, node.id])).toEqual([
            ['tool', '1::tool::Ended'],
            ['ended', '1::ended::Ended'],
        ])
        expect(graph.links.filter((link) => link.target === '1::tool::Ended').map((link) => link.value)).toEqual([2])
        expect(graph.links.filter((link) => link.target === '1::ended::Ended').map((link) => link.value)).toEqual([3])
    })

    it('describes a leak path with one Ended for its padding and keeps a tool named Ended', () => {
        expect(describeJourneyPath({ steps: ['sql', null, null], outcome: 'error', count: 1 })).toBe('sql → Ended')
        expect(describeJourneyPath({ steps: ['Ended', null, null], outcome: 'error', count: 1 })).toBe('Ended → Ended')
    })
})
