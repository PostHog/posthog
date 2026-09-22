import type { MCPIntentClusterJourneyPathApi } from '../generated/api.schemas'
import { buildJourneyGraph } from './clusterJourneyGraph'

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
            '0::Init',
            '1::schema',
            '2::sql',
            '3::Ended',
            '4::Completed',
            '4::Error',
            '1::sql',
            '2::Ended',
        ])
        const schemaToSql = graph.links.filter((l) => l.source === '1::schema' && l.target === '2::sql')
        expect(schemaToSql.map((l) => [l.meta?.outcome, l.value])).toEqual([
            ['completed', 20],
            ['error', 5],
        ])
        const intoError = graph.links.filter((l) => l.target === '4::Error')
        expect(intoError.reduce((sum, l) => sum + l.value, 0)).toBe(8)
    })
})
