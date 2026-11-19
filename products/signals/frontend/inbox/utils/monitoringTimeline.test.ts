import type {
    ReportMonitoringOutcomeApi,
    ReportMonitoringSummaryApi,
    SignalReportListApi,
} from 'products/signals/frontend/generated/api.schemas'

import { monitoringListParams } from '../logics/monitoringTabLogic'
import {
    monitoringAxis,
    monitoringEvidence,
    monitoringReadingOverdue,
    monitoringRowStatus,
    sortByVerdict,
} from './monitoringTimeline'

const NOW = Date.parse('2026-11-18T17:00:00Z')
const HOUR = 3_600_000
const at = (hours: number): string => new Date(NOW + hours * HOUR).toISOString()

function summary(
    state: ReportMonitoringSummaryApi['state'],
    endsInHours: number,
    nextMeasurementInHours: number | null = null
): ReportMonitoringSummaryApi {
    return {
        state,
        started_at: at(-24),
        ends_at: at(endsInHours),
        checks: [],
        lead_check:
            nextMeasurementInHours === null
                ? null
                : {
                      check_id: 'check',
                      title: 'Errors stay low',
                      metric_id: null,
                      metric_kind: 'occurrences',
                      value_format: 'count',
                      unit: null,
                      comparison: { operator: 'lte', value: 10 },
                      monitoring: { reference_period_minutes: 1440, threshold_scaling: 'linear' },
                      baseline_value: null,
                      ends_at: at(endsInHours),
                      next_measurement_at: at(nextMeasurementInHours),
                      readings: [],
                  },
    }
}

function report(
    id: string,
    fields: {
        summary?: ReportMonitoringSummaryApi | null
        outcome?: ReportMonitoringOutcomeApi | null
    }
): SignalReportListApi {
    const partial: Partial<SignalReportListApi> = {
        id,
        monitoring_started_at: at(-24),
        monitoring_summary: fields.summary ?? null,
        monitoring_outcome: fields.outcome ?? null,
    }
    return partial as SignalReportListApi
}

const outcome = (
    kind: ReportMonitoringOutcomeApi['kind'],
    endedHoursAgo: number,
    followUp = false
): ReportMonitoringOutcomeApi => ({
    kind,
    ended_at: at(-endedHoursAgo),
    follow_up: followUp ? { report_id: 'follow-up', title: 'Still failing', status: 'ready' } : null,
})

describe('monitoringTimeline', () => {
    test.each([
        ['every check passed', report('a', { outcome: outcome('resolved', 2) }), 'Resolved'],
        ['an assessment decided', report('a', { outcome: outcome('resolved_by_assessment', 2) }), 'Resolved'],
        ['a person resolved it', report('a', { outcome: outcome('resolved_manually', 2) }), 'Verified manually'],
        ['every check was canceled', report('a', { outcome: outcome('resolved_unverified', 2) }), 'Not verified'],
        ['closed with a follow-up', report('a', { outcome: outcome('closed', 2, true) }), 'Follow-up opened'],
        ['closed before grouping linked a follow-up', report('a', { outcome: outcome('closed', 2) }), 'Closed'],
        ['agent checks only', report('a', { summary: summary('final_check_only', 10) }), 'Watching'],
        ['no reading yet', report('a', { summary: summary('awaiting_reading', 10) }), 'Watching'],
        ['off target', report('a', { summary: summary('not_on_track', 10) }), 'Not on track'],
        ['window ended since the page loaded', report('a', { summary: summary('on_track', -1) }), 'Verifying'],
        ['no summary', report('a', {}), 'Watching'],
    ])('row status when %s', (_, row, label) => {
        expect(monitoringRowStatus(row, NOW).label).toBe(label)
    })

    test('orders finished reports first, then the soonest verdict, and reports without a window last', () => {
        const rows = [
            report('later', { summary: summary('on_track', 48) }),
            report('no-window', {}),
            report('finished', { outcome: outcome('resolved', 30) }),
            report('sooner', { summary: summary('on_track', 3) }),
        ]

        expect(sortByVerdict(rows).map((row) => row.id)).toEqual(['finished', 'sooner', 'later', 'no-window'])
    })

    test.each([
        ['due over half an hour ago', -2, 10, true],
        ['due a few minutes ago', -0.1, 10, false],
        ['due later', 3, 10, false],
        ['window already ended', -2, -1, false],
    ])('a reading counts as overdue when %s', (_, nextInHours, endsInHours, overdue) => {
        const row = report('a', { summary: summary('on_track', endsInHours, nextInHours) })
        expect(monitoringReadingOverdue(row, NOW)).toBe(overdue)
    })

    test('widens the axis to every window and verdict on the page, within bounds', () => {
        const finishedTenDaysAgo = report('a', { outcome: outcome('resolved', 240) })
        const longWindow = report('b', { summary: summary('on_track', 24 * 40) })

        expect(monitoringAxis([], NOW)).toEqual({ start: NOW - 7 * 24 * HOUR, end: NOW + 4 * 24 * HOUR })
        expect(monitoringAxis([finishedTenDaysAgo], NOW).start).toBe(NOW - 7 * 24 * HOUR)
        expect(
            monitoringAxis([{ ...finishedTenDaysAgo, monitoring_started_at: at(-264) } as SignalReportListApi], NOW)
                .start
        ).toBe(NOW - 264 * HOUR)
        expect(monitoringAxis([longWindow], NOW).end).toBe(NOW + 30 * 24 * HOUR)
    })

    test('draws a chart only when the lead check has a metric snapshot that places the fix', () => {
        const withMetric = (bucketCount: number): SignalReportListApi =>
            ({
                ...report('a', {
                    summary: {
                        ...summary('on_track', 10, 2),
                        lead_check: { ...summary('on_track', 10, 2).lead_check!, metric_id: 'errors' },
                    },
                }),
                metrics: [
                    {
                        metric_id: 'errors',
                        title: 'Errors',
                        kind: 'occurrences',
                        value_at: at(-0.25),
                        series: Array.from({ length: bucketCount }, () => 3),
                        series_buckets: Array.from({ length: bucketCount }, (_, i) => at(i - bucketCount + 1)),
                        value_format: 'count',
                        interval: 'hour',
                    },
                ],
            }) as SignalReportListApi

        expect(monitoringEvidence(report('agent-only', { summary: summary('final_check_only', 10) }), 'UTC')).toBeNull()
        expect(monitoringEvidence(withMetric(30), 'UTC')?.trend.fixIndex).toBe(5)
        // One bucket cannot show a before and an after.
        expect(monitoringEvidence(withMetric(1), 'UTC')).toBeNull()
    })

    test.each([
        [{ everyone: true, connections: ['assigned' as const] }, undefined],
        [
            { everyone: false, connections: ['assigned' as const, 'suggested_reviewer' as const] },
            'assigned,suggested_reviewer',
        ],
    ])('list params for scope %o', (scope, connected) => {
        expect(monitoringListParams(scope)).toEqual({
            view: 'monitoring_recent',
            limit: 100,
            offset: 0,
            include_source_metadata: false,
            ...(connected ? { connected } : {}),
        })
    })
})
