import type { SignalReportCheckProgressApi } from 'products/signals/frontend/generated/api.schemas'

export const reportCheckProgressFixture: SignalReportCheckProgressApi = {
    check_id: 'expected-impact-check',
    status: 'on_track',
    explanation: 'Compared with the target for the time elapsed. This is a provisional pace estimate.',
    started_at: '2026-08-27T12:00:00Z',
    ended_at: '2026-08-29T12:00:00Z',
    measured_at: '2026-08-29T12:00:00Z',
    value: 4,
    target: (50 * 2) / 14,
    target_upper: null,
    target_type: 'proportional',
    sample_size: 4,
    query: {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            series: [{ kind: 'EventsNode', event: 'example_failure', math: 'dau' }],
            dateRange: {
                date_from: '2026-08-27T12:00:00Z',
                date_to: '2026-08-29T12:00:00Z',
                explicitDate: true,
            },
            interval: 'day',
        },
    },
    points: [
        { at: '2026-08-27T12:00:00Z', value: 1, target: 50 / 14, target_upper: null },
        { at: '2026-08-28T12:00:00Z', value: 3, target: 50 / 14, target_upper: null },
    ],
}
