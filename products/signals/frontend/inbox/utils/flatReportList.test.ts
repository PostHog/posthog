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
        'outcome-monitoring': [],
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
    const plan = (lead: string): NonNullable<SignalReport['link_summary']>['plan'] => ({
        id: 'plan',
        title: 'plan',
        status: 'ready',
        steps: ['layer-1', 'layer-2', 'layer-3'].map((id) => ({ id, title: id, state: 'waiting' as const })),
        lead_step_id: lead,
        position: null,
    })
    const planRow = (id: string, key: number, lead: string): SignalReport =>
        report(id, {
            inbox_merge_key: key,
            link_summary: {
                kind: id === 'plan' ? 'plan' : 'part_of',
                report: null,
                also_follow_up: false,
                plan: plan(lead),
                other_links: [],
            },
        })

    // A plan shows once, at its best-ranked loaded row, as its lead layer when that layer is loaded.
    it.each([
        {
            name: 'the lead layer takes the best rank of the plan',
            rows: [
                planRow('layer-1', 1, 'layer-3'),
                report('other', { inbox_merge_key: 2 }),
                planRow('layer-3', 3, 'layer-3'),
                planRow('plan', 4, 'layer-3'),
            ],
            expected: [
                ['layer-3', ['layer-1', 'plan']],
                ['other', []],
            ],
        },
        {
            name: 'the best-ranked layer stands in when the lead is not loaded',
            rows: [planRow('plan', 1, 'layer-1'), planRow('layer-2', 2, 'layer-1'), planRow('layer-3', 3, 'layer-1')],
            expected: [['layer-2', ['plan', 'layer-3']]],
        },
        {
            name: 'the plan shows itself when no layer is loaded',
            rows: [report('other', { inbox_merge_key: 1 }), planRow('plan', 2, 'layer-1')],
            expected: [
                ['other', []],
                ['plan', []],
            ],
        },
    ])('collapses plan layers: $name', ({ rows, expected }) => {
        const merged = mergeReportRows(sections({ 'needs-decision': rows }), ['needs-decision'], 'recommended', 'asc', {
            collapsePlans: true,
        })

        expect(merged.map((row) => [row.report.id, row.collapsedReportIds ?? []])).toEqual(expected)
    })
})
