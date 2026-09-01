import { SignalReport, SignalReportStatus } from '../types'
import { compareSignalReports } from './reportOrdering'

function report(id: string, overrides: Partial<SignalReport>): SignalReport {
    return {
        id,
        title: id,
        summary: null,
        status: SignalReportStatus.READY,
        total_weight: 0,
        signal_count: 1,
        relevant_user_count: null,
        artefact_count: 0,
        is_suggested_reviewer: false,
        priority: 'P2',
        created_at: '2026-06-01T10:00:00Z',
        updated_at: '2026-06-01T10:00:00Z',
        ...overrides,
    }
}

describe('compareSignalReports', () => {
    // The merged list must order rows from different per-state responses the way the server ordered
    // each response, or reports jump around relative to the sectioned queries they came from.
    it('sorts by priority, then status rank, then recency', () => {
        const rows = [
            report('resolved-p0', { priority: 'P0', status: SignalReportStatus.RESOLVED }),
            report('ready-p2-old', { priority: 'P2', updated_at: '2026-06-01T10:00:00Z' }),
            report('ready-p2-new', { priority: 'P2', updated_at: '2026-06-02T10:00:00Z' }),
            report('unprioritized', { priority: null }),
            report('ready-p0', { priority: 'P0' }),
            report('not-actionable-p0', { priority: 'P0', actionability: 'not_actionable' }),
        ]
        rows.sort(compareSignalReports('priority', 'asc'))
        expect(rows.map((r) => r.id)).toEqual([
            // Within P0: ready (rank 0) before ready-not-actionable (1) before resolved (7).
            'ready-p0',
            'not-actionable-p0',
            'resolved-p0',
            // Within P2: newer updated_at first.
            'ready-p2-new',
            'ready-p2-old',
            // Missing priority coalesces after P4, like the server's "~".
            'unprioritized',
        ])
    })

    it('flips only the selected field for desc, keeping the status and recency tiebreaks', () => {
        const rows = [
            report('old-resolved', { created_at: '2026-06-01T00:00:00Z', status: SignalReportStatus.RESOLVED }),
            report('new-ready', { created_at: '2026-06-03T00:00:00Z' }),
            report('new-resolved', { created_at: '2026-06-03T00:00:00Z', status: SignalReportStatus.RESOLVED }),
        ]
        rows.sort(compareSignalReports('created_at', 'desc'))
        expect(rows.map((r) => r.id)).toEqual(['new-ready', 'new-resolved', 'old-resolved'])
    })

    // DRF omits the fractional seconds when the microseconds are zero, and plain string order then
    // puts the zero-microsecond row after every fractional one in the same second.
    it('orders zero-microsecond timestamps against fractional ones like the database', () => {
        const rows = [
            report('fractional', { created_at: '2026-06-01T00:00:00.100000Z' }),
            report('whole-second', { created_at: '2026-06-01T00:00:00Z' }),
        ]
        rows.sort(compareSignalReports('created_at', 'asc'))
        expect(rows.map((r) => r.id)).toEqual(['whole-second', 'fractional'])
        rows.sort(compareSignalReports('created_at', 'desc'))
        expect(rows.map((r) => r.id)).toEqual(['fractional', 'whole-second'])
    })
})
