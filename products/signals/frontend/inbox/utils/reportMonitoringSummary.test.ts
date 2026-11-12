import type {
    MonitoringLeadCheckApi,
    ReportMetricApi,
    ReportMonitoringSummaryApi,
} from 'products/signals/frontend/generated/api.schemas'

import {
    latestMergedPullRequest,
    monitoringDisplayState,
    monitoringFigures,
    monitoringPullRequestStatus,
    monitoringTrend,
    monitoringWindowProgress,
} from './reportMonitoringSummary'

const STARTED_AT = '2026-11-06T18:00:00Z'

function lead(overrides: Partial<MonitoringLeadCheckApi> = {}): MonitoringLeadCheckApi {
    return {
        check_id: 'check',
        title: 'Errors stay low',
        metric_id: 'errors',
        metric_kind: 'occurrences',
        value_format: 'count',
        unit: 'calls',
        comparison: { operator: 'lte', value: 70 },
        monitoring: {
            reference_period_minutes: 7 * 1440,
            threshold_scaling: 'linear',
            baseline_period_minutes: 7 * 1440,
        },
        baseline_value: 280,
        ends_at: '2026-11-13T18:00:00Z',
        next_measurement_at: null,
        readings: [{ measured_at: '2026-11-08T18:00:00Z', matches: false, observed_value: 30, threshold: 20 }],
        ...overrides,
    }
}

function summary(
    leadCheck: MonitoringLeadCheckApi | null = lead(),
    startedAt: string = STARTED_AT
): ReportMonitoringSummaryApi {
    return { state: 'not_on_track', started_at: startedAt, ends_at: '2026-11-13T18:00:00Z', lead_check: leadCheck }
}

const DAILY_BUCKETS = ['2026-11-04', '2026-11-05', '2026-11-06', '2026-11-07', '2026-11-08', '2026-11-09']

function metric(
    overrides: Partial<ReportMetricApi> & { interval?: string } = {}
): ReportMetricApi & { interval: string } {
    return {
        metric_id: 'errors',
        title: 'Errors',
        kind: 'occurrences',
        value: 1,
        value_at: '2026-11-09T12:00:00Z',
        series: [9, 8, 9, 7, 2, 1],
        series_buckets: DAILY_BUCKETS,
        value_format: 'count',
        unit: 'calls',
        interval: 'day',
        ...overrides,
    }
}

describe('Monitoring summary on an inbox row', () => {
    it.each([
        ['in UTC', 'UTC', summary(), metric(), 2],
        // 18:00 UTC on Nov 6 is already Nov 7 in Tokyo, so the fix lands one daily bucket later.
        ['in the team timezone', 'Asia/Tokyo', summary(), metric(), 3],
        [
            'after a day the query skips',
            'UTC',
            summary(lead(), '2026-11-07T12:00:00Z'),
            metric({ series: [9, 8, 9, 2], series_buckets: ['2026-11-04', '2026-11-05', '2026-11-06', '2026-11-09'] }),
            3,
        ],
        [
            'in the week Trends started on Monday',
            'UTC',
            summary(lead(), '2026-11-08T18:00:00Z'),
            metric({ series: [9, 8, 2], series_buckets: ['2026-10-26', '2026-11-02', '2026-11-09'], interval: 'week' }),
            1,
        ],
    ])('places the fix in the bucket it happened in, %s', (_name, timezone, monitoring, snapshot, fixIndex) => {
        expect(monitoringTrend(monitoring, snapshot, timezone)?.fixIndex).toBe(fixIndex)
    })

    it.each([
        ['a snapshot measured before the fix', metric({ value_at: '2026-11-06T12:00:00Z' })],
        [
            'a series that ends before the fix',
            metric({
                series_buckets: ['2026-10-30', '2026-10-31', '2026-11-01', '2026-11-02', '2026-11-03', '2026-11-04'],
            }),
        ],
        ['a snapshot without bucket dates', metric({ series_buckets: null })],
        ['negative values', metric({ series: [-3, -2, -1, -1, -1, -1] })],
    ])('draws no trend from %s', (_name, snapshot) => {
        expect(monitoringTrend(summary(), snapshot, 'UTC')).toBeNull()
    })

    it.each([
        ['before the window ends', '2026-11-13T17:59:00Z', 'not_on_track'],
        ['once the window has ended', '2026-11-13T18:00:00Z', 'window_ended'],
    ])('reads the state %s', (_name, now, expected) => {
        expect(monitoringDisplayState(summary(), Date.parse(now))).toBe(expected)
    })

    it('counts the window from the latest merge', () => {
        const first = { merged: true, merged_at: '2026-11-05T10:00:00Z' }
        const latest = { merged: true, merged_at: '2026-11-06T18:00:00Z' }
        expect(latestMergedPullRequest([first, { merged: false, merged_at: null }, latest])).toBe(latest)
    })

    it.each([
        ['a merge with its time', { merged: true, merged_at: '2026-11-07T10:00:00Z', state: 'merged' }, 'merged Nov 7'],
        ['a merge without its time', { merged: true, merged_at: null, state: 'merged' }, 'merged Nov 6'],
        ['an open PR after a manual completion', { merged: false, merged_at: null, state: 'open' }, 'open'],
        ['an unknown state', { merged: false, merged_at: null, state: 'unknown' }, null],
    ])('describes the PR for %s', (_name, pullRequest, expected) => {
        expect(monitoringPullRequestStatus(pullRequest, STARTED_AT)).toBe(expected)
    })

    it.each([
        ['a linear count scales to one bucket', lead(), 10],
        [
            'a fixed rate holds for every bucket',
            lead({
                value_format: 'percentage_scaled',
                metric_kind: 'error_rate',
                comparison: { operator: 'lte', value: 0.02 },
                monitoring: { reference_period_minutes: 480, threshold_scaling: 'fixed' },
            }),
            0.02,
        ],
        [
            'a fixed count over the period has no per-bucket target',
            lead({ monitoring: { reference_period_minutes: 7 * 1440, threshold_scaling: 'fixed' } }),
            null,
        ],
    ])('target line: %s', (_name, leadCheck, target) => {
        expect(monitoringTrend(summary(leadCheck), metric(), 'UTC')?.target).toBe(target)
    })

    it.each([
        ['a linear count per day', lead(), { before: '40 calls', sinceFix: '15 calls' }],
        [
            'a rate as measured',
            lead({
                value_format: 'percentage_scaled',
                metric_kind: 'error_rate',
                unit: null,
                baseline_value: 0.3,
                comparison: { operator: 'lte', value: 0.02 },
                monitoring: { reference_period_minutes: 480, threshold_scaling: 'fixed' },
                readings: [
                    { measured_at: '2026-11-07T00:00:00Z', matches: true, observed_value: 0.014, threshold: 0.02 },
                ],
            }),
            { before: '30%', sinceFix: '1.4%' },
        ],
        [
            'a fixed count as totals over their own periods',
            lead({
                monitoring: {
                    reference_period_minutes: 7 * 1440,
                    threshold_scaling: 'fixed',
                    baseline_period_minutes: 7 * 1440,
                },
            }),
            { before: '280 calls in 7 days', sinceFix: '30 calls so far' },
        ],
    ])('compares before and since the fix for %s', (_name, leadCheck, expected) => {
        expect(monitoringFigures(summary(leadCheck), 'day')).toMatchObject(expected)
    })

    it.each([
        ['a week-long window', '2026-11-13T18:00:00Z', '2026-11-09T19:00:00Z', 'Day 4 of 7'],
        ['a day-long window', '2026-11-07T18:00:00Z', '2026-11-07T10:30:00Z', 'Hour 17 of 24'],
        ['an ended window', '2026-11-07T18:00:00Z', '2026-11-08T00:00:00Z', null],
    ])('shows progress through %s', (_name, endsAt, now, expected) => {
        expect(monitoringWindowProgress({ ...summary(), ends_at: endsAt }, Date.parse(now))).toBe(expected)
    })
})
