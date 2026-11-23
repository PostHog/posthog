import type {
    MonitoringCheckSummaryApi,
    MonitoringLeadCheckApi,
    ReportMetricListApi,
    ReportMonitoringOutcomeApi,
    ReportMonitoringSummaryApi,
} from 'products/signals/frontend/generated/api.schemas'

import { SignalReport, SignalReportStatus } from '../types'
import { makeReport, myClaim } from './inboxMocks'

/** Every relative time in these fixtures is measured from here; pin stories to it with `mockDate`. */
export const MONITORING_MOCK_NOW = '2026-11-18T17:00:00Z'

const NOW = Date.parse(MONITORING_MOCK_NOW)
const HOUR = 3_600_000
const at = (hours: number): string => new Date(NOW + hours * HOUR).toISOString()

type MonitoringRow = SignalReport & {
    monitoring_ended_at: string | null
    monitoring_outcome: ReportMonitoringOutcomeApi | null
}

function hourlyMetric(
    id: string,
    title: string,
    format: 'count' | 'percentage_scaled',
    series: number[]
): ReportMetricListApi {
    return {
        metric_id: id,
        title,
        kind: format === 'count' ? 'occurrences' : 'error_rate',
        role: 'primary',
        value: series[series.length - 1],
        value_at: at(-0.25),
        series,
        series_buckets: series.map((_, index) => at(index - series.length + 1).replace(/:\d\d:\d\d\.\d+Z$/, ':00:00Z')),
        value_format: format,
        unit: format === 'count' ? 'errors' : null,
        interval: 'hour',
    } as ReportMetricListApi
}

function lead(
    fields: Partial<MonitoringLeadCheckApi> & Pick<MonitoringLeadCheckApi, 'check_id' | 'title'>
): MonitoringLeadCheckApi {
    return {
        metric_id: null,
        metric_kind: 'occurrences',
        value_format: 'count',
        unit: null,
        comparison: { operator: 'lte', value: 40 },
        monitoring: { reference_period_minutes: 1440, threshold_scaling: 'linear', baseline_period_minutes: 1440 },
        baseline_value: null,
        ends_at: at(8),
        next_measurement_at: null,
        readings: [],
        ...fields,
    }
}

function check(
    id: string,
    title: string,
    state: MonitoringCheckSummaryApi['state'],
    endsInHours: number,
    kind: MonitoringCheckSummaryApi['kind'] = 'metric_threshold'
): MonitoringCheckSummaryApi {
    return { check_id: id, title, kind, state, ends_at: at(endsInHours) }
}

function summary(
    state: ReportMonitoringSummaryApi['state'],
    startedHoursAgo: number,
    endsInHours: number,
    checks: MonitoringCheckSummaryApi[],
    leadCheck: MonitoringLeadCheckApi | null = null
): ReportMonitoringSummaryApi {
    return { state, started_at: at(-startedHoursAgo), ends_at: at(endsInHours), lead_check: leadCheck, checks }
}

let prNumber = 5100
function row(
    fields: Partial<SignalReport> & { title: string; startedHoursAgo: number },
    monitoring: { summary?: ReportMonitoringSummaryApi | null; outcome?: ReportMonitoringOutcomeApi | null }
): MonitoringRow {
    prNumber += 3
    const { startedHoursAgo, ...rest } = fields
    return {
        ...makeReport({
            status: monitoring.outcome
                ? monitoring.outcome.kind === 'closed'
                    ? SignalReportStatus.CLOSED
                    : SignalReportStatus.RESOLVED
                : SignalReportStatus.MONITORING,
            implementation_pr_url: `https://github.com/example/app/pull/${prNumber}`,
            implementation_pr_merged: true,
            monitoring_started_at: at(-startedHoursAgo),
            ...rest,
        }),
        monitoring_summary: monitoring.summary ?? null,
        monitoring_outcome: monitoring.outcome ?? null,
        monitoring_ended_at: monitoring.outcome?.ended_at ?? null,
    }
}

export const monitoringRows: MonitoringRow[] = [
    row(
        {
            title: 'fix(exports): Stop the nightly export retrying files that already finished',
            summary_lead: 'Finished exports were queued again after a worker restart.',
            startedHoursAgo: 90,
        },
        {
            outcome: { kind: 'resolved', ended_at: at(-18), follow_up: null },
            summary: summary('window_ended', 90, -18, [
                check('export-agent', 'An agent confirms no export is delivered twice', 'passed', -18, 'agent'),
            ]),
        }
    ),
    row(
        {
            title: 'fix(invites): Resend invite emails that bounced on a full mailbox',
            summary_lead: 'Invites that bounced once were never sent again, so teammates never joined.',
            startedHoursAgo: 140,
        },
        {
            outcome: {
                kind: 'closed',
                ended_at: at(-60),
                follow_up: {
                    report_id: 'follow-up-signup',
                    title: 'Bounced invites are still not resent',
                    status: 'ready',
                },
            },
            summary: summary('window_ended', 140, -60, [
                check('invite-check', 'Bounced invites without a resend stay at or below 5 in 3 days', 'failed', -60),
            ]),
        }
    ),
    row(
        {
            title: 'fix(billing): Apply the annual discount when a plan renews',
            summary_lead: 'Annual plans renewed at the monthly price because the discount was dropped on renewal.',
            startedHoursAgo: 14,
            assignee: myClaim,
        },
        {
            summary: summary('window_ended', 14, -2, [
                check('renewal-errors', 'Renewal pricing errors stay at or below 5 in 12 hours', 'passed', -2),
                check('renewal-discount', 'Annual renewals keep their discount', 'awaiting_reading', -2),
                check(
                    'renewal-agent',
                    'An agent confirms no tickets mention a wrong renewal price',
                    'final_check_only',
                    -2,
                    'agent'
                ),
            ]),
        }
    ),
    row(
        {
            title: 'fix(search): Stop the search page logging an error for every empty result',
            summary_lead: 'An empty result was treated as a failure, so every search with no matches logged an error.',
            startedHoursAgo: 16,
            metrics: [
                hourlyMetric(
                    'search-errors',
                    'Search page errors',
                    'count',
                    [
                        24, 27, 22, 30, 26, 25, 28, 31, 29, 24, 26, 27, 23, 2, 1, 0, 2, 1, 1, 0, 2, 1, 0, 1, 1, 0, 1, 2,
                        1, 1,
                    ]
                ),
            ] as SignalReport['metrics'],
        },
        {
            summary: summary(
                'on_track',
                16,
                8,
                [check('search-check', 'Search page errors stay at or below 40 a day', 'on_track', 8)],
                lead({
                    check_id: 'search-check',
                    title: 'Search page errors stay at or below 40 a day',
                    metric_id: 'search-errors',
                    unit: 'errors',
                    baseline_value: 620,
                    next_measurement_at: at(2),
                    readings: [
                        { measured_at: at(-10), matches: true, observed_value: 6, threshold: 10 },
                        { measured_at: at(-4), matches: true, observed_value: 11, threshold: 20 },
                    ],
                })
            ),
        }
    ),
    row(
        {
            title: 'fix(uploads): Retry image uploads that time out on slow connections',
            summary_lead: 'Uploads over slow connections hit a short timeout and failed without a retry.',
            startedHoursAgo: 11,
            assignee: myClaim,
            metrics: [
                hourlyMetric(
                    'upload-failures',
                    'Image upload failure rate',
                    'percentage_scaled',
                    [
                        0.09, 0.1, 0.08, 0.09, 0.11, 0.1, 0.09, 0.1, 0.08, 0.09, 0.1, 0.09, 0.1, 0.09, 0.09, 0.08, 0.1,
                        0.09, 0.05, 0.04, 0.045, 0.04, 0.038, 0.042, 0.04, 0.041, 0.04, 0.043, 0.039, 0.041,
                    ]
                ),
            ] as SignalReport['metrics'],
        },
        {
            summary: summary(
                'not_on_track',
                11,
                13,
                [check('upload-check', 'Image upload failure rate stays at or below 2%', 'not_on_track', 13)],
                lead({
                    check_id: 'upload-check',
                    title: 'Image upload failure rate stays at or below 2%',
                    metric_id: 'upload-failures',
                    metric_kind: 'error_rate',
                    value_format: 'percentage_scaled',
                    comparison: { operator: 'lte', value: 0.02 },
                    monitoring: {
                        reference_period_minutes: 1440,
                        threshold_scaling: 'fixed',
                        baseline_period_minutes: 1440,
                    },
                    baseline_value: 0.093,
                    ends_at: at(13),
                    next_measurement_at: at(1),
                    readings: [{ measured_at: at(-5), matches: false, observed_value: 0.041, threshold: 0.02 }],
                })
            ),
        }
    ),
    row(
        {
            title: 'fix(alerts): Send one alert per threshold breach, not one per check run',
            summary_lead: 'A breached alert sent a notification on every check run until someone acknowledged it.',
            startedHoursAgo: 30,
        },
        {
            summary: summary('final_check_only', 30, 66, [
                check(
                    'alerts-agent',
                    'An agent confirms each breach sends one notification',
                    'final_check_only',
                    66,
                    'agent'
                ),
            ]),
        }
    ),
]
