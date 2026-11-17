import type { MCPIntentClusterToolEntryApi } from '../generated/api.schemas'
import { clusterLabel, longTailLabel, topToolNames } from './clusterRanking'

function entry(tool: string, count: number): MCPIntentClusterToolEntryApi {
    return { tool, count, pct: 0, errors: 0, error_rate_pct: 0 }
}

describe('clusterRanking', () => {
    it('topToolNames returns the three busiest tools even when the distribution arrives unsorted', () => {
        const tool_distribution = [entry('d', 1), entry('b', 30), entry('a', 50), entry('c', 20)]

        expect(topToolNames({ tool_distribution })).toEqual(['a', 'b', 'c'])
    })

    it.each([
        ['a real label', { id: 4, label: 'Debug slow queries' }, 'Debug slow queries'],
        ['a label redacted to empty', { id: 4, label: '' }, 'Intent group 4'],
        ['a whitespace-only label', { id: 9, label: '  ' }, 'Intent group 9'],
    ])('clusterLabel for %s', (_, cluster, expected) => {
        expect(clusterLabel(cluster)).toBe(expected)
    })

    it.each([
        [1, 'Long tail: 1 one-off intent'],
        [1234, 'Long tail: 1,234 one-off intents'],
    ])('longTailLabel(%s)', (intent_count, expected) => {
        expect(longTailLabel({ intent_count })).toBe(expected)
    })
})
