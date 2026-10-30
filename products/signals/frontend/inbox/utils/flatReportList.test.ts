import { InboxReportSectionKey, SignalReport, SignalReportStatus } from '../types'
import { mergeReportRows } from './flatReportList'

function report(id: string, overrides: Partial<SignalReport> = {}): SignalReport {
    return {
        id,
        title: id,
        summary: null,
        status: SignalReportStatus.READY,
        total_weight: 0,
        signal_count: 1,
        artefact_count: 0,
        is_suggested_reviewer: false,
        priority: 'P2',
        created_at: '2026-06-01T10:00:00Z',
        updated_at: '2026-06-01T10:00:00Z',
        ...overrides,
    }
}

function sections(
    rows: Partial<Record<InboxReportSectionKey, SignalReport[]>>
): Record<InboxReportSectionKey, SignalReport[]> {
    return {
        monitoring: [],
        'needs-decision': [],
        resolved: [],
        closed: [],
        dismissed: [],
        'held-back': [],
        'not-actionable': [],
        ...rows,
    }
}

describe('mergeReportRows', () => {
    // The server orders a Recommended response by the raw score, so the coarse key is not monotonic
    // within one response. A plain sort by key would undo that order.
    it('merges Recommended responses by the merge key and keeps each response in server order', () => {
        const rows = mergeReportRows(
            sections({
                monitoring: [
                    report('m-key-9', { inbox_merge_key: 9 }),
                    report('m-key-6', { inbox_merge_key: 6 }),
                    report('m-unkeyed', { inbox_merge_key: null }),
                ],
                'needs-decision': [
                    report('n-key-3', { inbox_merge_key: 3, priority: 'P4' }),
                    report('n-key-9', { inbox_merge_key: 9, priority: 'P0' }),
                    report('n-key-20', { inbox_merge_key: 20 }),
                ],
            }),
            ['monitoring', 'needs-decision'],
            'recommended',
            'asc'
        )

        expect(rows.map((row) => [row.report.id, row.sectionKey])).toEqual([
            ['n-key-3', 'needs-decision'],
            ['m-key-9', 'monitoring'],
            ['m-key-6', 'monitoring'],
            ['n-key-9', 'needs-decision'],
            ['n-key-20', 'needs-decision'],
            ['m-unkeyed', 'monitoring'],
        ])
    })
})
