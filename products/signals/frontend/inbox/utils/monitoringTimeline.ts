import type { LemonTagType } from '@posthog/lemon-ui'

import type { TrendsQuery } from '~/queries/schema/schema-general'

import type { SignalReportListApi } from 'products/signals/frontend/generated/api.schemas'

import {
    MONITORING_SUMMARY_TAGS,
    type MonitoringTrend,
    monitoringDisplayState,
    monitoringTrend,
} from './reportMonitoringSummary'

const HOUR_MS = 3_600_000
const DAY_MS = 24 * HOUR_MS

/** The timeline shows the last week, where most windows started, and the next few days, where most verdicts land. */
export const MONITORING_AXIS_PAST_MS = 7 * DAY_MS
export const MONITORING_AXIS_FUTURE_MS = 4 * DAY_MS

export interface MonitoringRowStatus {
    label: string
    type: LemonTagType
    description: string
}

export function monitoringRowStatus(report: SignalReportListApi, now: number): MonitoringRowStatus {
    const outcome = report.monitoring_outcome
    if (outcome) {
        switch (outcome.kind) {
            case 'resolved':
                return { label: 'Resolved', type: 'success', description: 'Every check passed with enough evidence.' }
            case 'resolved_by_assessment':
                return {
                    label: 'Resolved',
                    type: 'success',
                    description:
                        'The checks were inconclusive, and an agent confirmed the fix worked from other evidence.',
                }
            case 'resolved_manually':
                return {
                    label: 'Verified manually',
                    type: 'default',
                    description: 'A person resolved it before the checks decided.',
                }
            case 'closed':
                return outcome.follow_up
                    ? {
                          label: 'Follow-up opened',
                          type: 'warning',
                          description: 'The fix was not shown to work, so a new report is researching why.',
                      }
                    : {
                          label: 'Closed',
                          type: 'warning',
                          description: 'The fix was not shown to work. Follow-up research has been requested.',
                      }
        }
    }
    const summary = report.monitoring_summary
    if (!summary) {
        return { label: 'Watching', type: 'muted', description: 'PostHog checks this fix when its window ends.' }
    }
    const state = monitoringDisplayState(summary, now)
    const tag = MONITORING_SUMMARY_TAGS[state]
    // Nothing measured yet, or nothing measured until the window ends: either way PostHog is watching.
    if (state === 'final_check_only' || state === 'awaiting_reading') {
        return { label: 'Watching', type: 'muted', description: tag.description }
    }
    return { label: tag.label, type: tag.type, description: tag.description }
}

export type MonitoringBarTone = 'success' | 'warning' | 'strong' | 'faint'

export function monitoringBarTone(report: SignalReportListApi, now: number): MonitoringBarTone {
    const summary = report.monitoring_summary
    if (report.monitoring_outcome || !summary) {
        return 'faint'
    }
    switch (monitoringDisplayState(summary, now)) {
        case 'not_on_track':
            return 'warning'
        case 'on_track':
            return 'success'
        case 'window_ended':
            return 'strong'
        default:
            return 'faint'
    }
}

export function monitoringSpan(report: SignalReportListApi): { start: number; end: number | null } | null {
    const startedAt = report.monitoring_summary?.started_at ?? report.monitoring_started_at
    if (!startedAt) {
        return null
    }
    const end = report.monitoring_outcome?.ended_at ?? report.monitoring_summary?.ends_at ?? null
    return { start: Date.parse(startedAt), end: end ? Date.parse(end) : null }
}

export function axisPercent(time: number, axisStart: number, axisEnd: number): number {
    return Math.min(Math.max((time - axisStart) / (axisEnd - axisStart), 0), 1) * 100
}

/** Earliest verdict first, so finished reports lead and the soonest upcoming ones follow. Reports with no window go last. */
export function sortByVerdict(reports: readonly SignalReportListApi[]): SignalReportListApi[] {
    const verdictAt = (report: SignalReportListApi): number => monitoringSpan(report)?.end ?? Number.POSITIVE_INFINITY
    return [...reports].sort((a, b) => verdictAt(a) - verdictAt(b))
}

export function verdictsDueWithin(reports: readonly SignalReportListApi[], now: number, withinMs: number): number {
    return reports.filter((report) => {
        const end = monitoringSpan(report)?.end
        return !report.monitoring_outcome && end != null && end > now && end - now <= withinMs
    }).length
}

/** A reading was due more than half an hour ago and has not run. The verdict still lands on time. */
export function monitoringReadingOverdue(report: SignalReportListApi, now: number): boolean {
    const summary = report.monitoring_summary
    const next = summary?.lead_check?.next_measurement_at
    return (
        !report.monitoring_outcome &&
        !!summary &&
        !!next &&
        Date.parse(next) < now - HOUR_MS / 2 &&
        monitoringDisplayState(summary, now) !== 'window_ended'
    )
}

const CHART_INTERVALS = new Set(['minute', 'hour', 'day', 'week', 'month'])

export interface MonitoringEvidence {
    metric: SignalReportListApi['metrics'][number]
    interval: NonNullable<TrendsQuery['interval']>
    trend: MonitoringTrend
}

/**
 * The lead check's report metric from the row's stored snapshot, when that snapshot can place the
 * fix on its buckets. Null otherwise, and the open row shows the window strip instead of a chart.
 */
export function monitoringEvidence(report: SignalReportListApi, timezone: string): MonitoringEvidence | null {
    const summary = report.monitoring_summary
    const lead = summary?.lead_check
    const metric = lead?.metric_id ? report.metrics.find((m) => m.metric_id === lead.metric_id) : undefined
    const interval = metric?.interval
    if (!summary || !metric || !interval || !CHART_INTERVALS.has(interval) || !metric.series_buckets) {
        return null
    }
    const trend = monitoringTrend(summary, metric, timezone)
    return trend ? { metric, interval: interval as NonNullable<TrendsQuery['interval']>, trend } : null
}
