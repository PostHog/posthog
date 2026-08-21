import { GroupableSignal, groupReportSignals, shouldGroupSignals } from './signalGrouping'

function signal(id: string, sourceProduct: string, sourceType = 't'): GroupableSignal & { id: string } {
    return { id, source_product: sourceProduct, source_type: sourceType }
}

describe('signalGrouping', () => {
    it('keeps small evidence sets flat', () => {
        expect(shouldGroupSignals([signal('a', 'error_tracking'), signal('b', 'session_replay')])).toBe(false)
    })

    it('groups by source line in first-seen order, preserving in-group order', () => {
        const signals = [
            signal('e1', 'error_tracking', 'issue_created'),
            signal('r1', 'session_replay', 'session_problem'),
            signal('e2', 'error_tracking', 'issue_created'),
            signal('c1', 'conversations', 'ticket'),
            signal('e3', 'error_tracking', 'issue_created'),
        ]
        expect(shouldGroupSignals(signals)).toBe(true)
        const groups = groupReportSignals(signals)
        expect(groups.map((g) => g.sourceProduct)).toEqual(['error_tracking', 'session_replay', 'conversations'])
        expect(groups[0].signals.map((s) => s.id)).toEqual(['e1', 'e2', 'e3'])
    })

    it('counts mixed types from one product separately', () => {
        const signals = [
            signal('i1', 'error_tracking', 'issue_created'),
            signal('g1', 'error_tracking', 'issue_regressed'),
            signal('i2', 'error_tracking', 'issue_created'),
        ]
        expect(groupReportSignals(signals).map((g) => [g.sourceType, g.signals.length])).toEqual([
            ['issue_created', 2],
            ['issue_regressed', 1],
        ])
    })
})
