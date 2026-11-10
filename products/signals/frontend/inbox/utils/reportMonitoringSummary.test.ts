import type {
    MonitoringLeadCheckApi,
    ReportMetricApi,
    ReportMonitoringSummaryApi,
} from 'products/signals/frontend/generated/api.schemas'

import {
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

function metric(valueAt: string): ReportMetricApi & { interval: string } {
    return {
        metric_id: 'errors',
        title: 'Errors',
        kind: 'occurrences',
        value: 1,
        value_at: valueAt,
        series: [9, 8, 9, 7, 2, 1],
        value_format: 'count',
        unit: 'calls',
        interval: 'day',
    }
}

describe('Monitoring summary on an inbox row', () => {
    it.each([
        ['in UTC', 'UTC', '2026-11-09T12:00:00Z', 2],
        // 18:00 UTC on Nov 6 is already Nov 7 in Tokyo, so the fix lands one daily bucket later.
        ['in the team timezone', 'Asia/Tokyo', '2026-11-09T12:00:00Z', 3],
    ])('places the fix in the bucket it happened in, %s', (_name, timezone, valueAt, fixIndex) => {
        expect(monitoringTrend(summary(), metric(valueAt), timezone)?.fixIndex).toBe(fixIndex)
    })

    it.each([
        // Sunday Nov 8 is the last day of a Monday-start week, and the first of a Sunday-start week.
        ['Monday', 1, 1],
        ['Sunday', 0, 2],
    ])('places a weekly fix in the project week that starts on %s', (_name, weekStartDay, fixIndex) => {
        const weekly = { ...metric('2026-11-10T12:00:00Z'), series: [9, 8, 2], interval: 'week' }
        expect(monitoringTrend(summary(lead(), '2026-11-08T18:00:00Z'), weekly, 'UTC', weekStartDay)?.fixIndex).toBe(
            fixIndex
        )
    })

    it.each([
        ['a snapshot measured in an earlier bucket', metric('2026-11-05T12:00:00Z')],
        ['a snapshot measured earlier in the same bucket', metric('2026-11-06T12:00:00Z')],
        ['negative values', { ...metric('2026-11-09T12:00:00Z'), series: [-3, -2, -1] }],
    ])('draws no trend from %s', (_name, snapshot) => {
        expect(monitoringTrend(summary(), snapshot, 'UTC')).toBeNull()
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
        expect(monitoringTrend(summary(leadCheck), metric('2026-11-09T12:00:00Z'), 'UTC')?.target).toBe(target)
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
