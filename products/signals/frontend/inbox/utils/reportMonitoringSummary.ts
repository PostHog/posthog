import type { LemonTagType } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type {
    MonitoringLeadCheckApi,
    MonitoringSummaryStateEnumApi,
    ReportMetricApi,
    ReportMonitoringSummaryApi,
} from 'products/signals/frontend/generated/api.schemas'

import type { MonitoringTimeline } from '../components/detail/reportCheckObservations'
import { monitoringPeriodLabel } from '../components/detail/reportCheckPresentation'
import { formatReportMetricValue } from './reportMetrics'

const HOUR_MS = 3_600_000
const DAY_MS = 24 * HOUR_MS

const BUCKET_MINUTES: Partial<Record<string, number>> = { minute: 1, hour: 60, day: 1440 }
const BUCKET_INTERVALS = new Set(['minute', 'hour', 'day', 'week', 'month'])

/** "Day 4 of 7", or "Hour 17 of 24" for a window of about a day or less. Null once the window has ended. */
export function monitoringWindowProgress(summary: ReportMonitoringSummaryApi, now: number): string | null {
    const start = Date.parse(summary.started_at)
    const end = Date.parse(summary.ends_at)
    if (!(end > start) || now >= end) {
        return null
    }
    const span = end - start
    const elapsed = Math.max(0, now - start)
    if (span <= 1.5 * DAY_MS) {
        const hours = Math.round(span / HOUR_MS)
        return `Hour ${Math.min(hours, Math.max(1, Math.ceil(elapsed / HOUR_MS)))} of ${hours}`
    }
    const days = Math.round(span / DAY_MS)
    return `Day ${Math.min(days, Math.floor(elapsed / DAY_MS) + 1)} of ${days}`
}

export function monitoringTimeLeft(endsAt: string, now: number): string {
    const remaining = Date.parse(endsAt) - now
    if (!(remaining > 0)) {
        return 'Window ended'
    }
    const days = Math.floor(remaining / DAY_MS)
    const hours = Math.floor((remaining % DAY_MS) / HOUR_MS)
    if (days === 0) {
        return hours === 0 ? 'Under 1h left' : `${hours}h left`
    }
    return hours ? `${days}d ${hours}h left` : `${days}d left`
}

/** The strip's input: the whole Monitoring period, with the lead check's interim readings on it. */
export function monitoringSummaryTimeline(summary: ReportMonitoringSummaryApi, now: number): MonitoringTimeline {
    const start = Date.parse(summary.started_at)
    const end = Date.parse(summary.ends_at)
    const position = (time: number): number => Math.min(Math.max((time - start) / (end - start), 0), 1)
    const lead = summary.lead_check
    const next = lead?.next_measurement_at ?? null
    return {
        startedAt: summary.started_at,
        endsAt: summary.ends_at,
        nextMeasurementAt: next,
        nextPosition: next ? position(Date.parse(next)) : null,
        elapsed: position(now),
        now,
        measurements: (lead?.readings ?? []).map((reading) => ({
            id: reading.measured_at,
            measuredAt: reading.measured_at,
            position: position(Date.parse(reading.measured_at)),
            matches: reading.matches,
        })),
    }
}

function isRate(lead: MonitoringLeadCheckApi): boolean {
    return (
        lead.value_format === 'percentage' ||
        lead.value_format === 'percentage_scaled' ||
        lead.metric_kind === 'conversion_rate' ||
        lead.metric_kind === 'error_rate'
    )
}

/**
 * How a target over the reference period maps onto one bucket, mirroring the detail chart's target
 * lines: a linear target is an additive count, so it scales with bucket length; a fixed rate holds
 * for every bucket. A fixed count over the whole period has no per-bucket equivalent.
 */
function bucketTargetFactor(lead: MonitoringLeadCheckApi, interval: string | null): number | null {
    if (lead.monitoring.threshold_scaling === 'fixed') {
        return isRate(lead) ? 1 : null
    }
    const minutes = interval ? BUCKET_MINUTES[interval] : undefined
    return minutes ? minutes / lead.monitoring.reference_period_minutes : null
}

export interface MonitoringTrend {
    values: number[]
    /** Index of the bucket Monitoring started in. Bars from here on are since the fix. */
    fixIndex: number
    /** The target for one bucket, when the target has a per-bucket equivalent. */
    target: number | null
}

/**
 * The report metric's trailing buckets, split where Monitoring started. Null when the snapshot cannot
 * place the fix: no series, no bucket size, or a snapshot measured before Monitoring began.
 */
export function monitoringTrend(
    summary: ReportMonitoringSummaryApi,
    metric: (ReportMetricApi & { interval?: string | null }) | undefined,
    timezone: string
): MonitoringTrend | null {
    const lead = summary.lead_check
    const values = metric?.series?.filter((point) => Number.isFinite(point)) ?? []
    const interval = metric?.interval
    if (!lead || !metric?.value_at || values.length < 2 || !interval || !BUCKET_INTERVALS.has(interval)) {
        return null
    }
    const unit = interval as 'minute' | 'hour' | 'day' | 'week' | 'month'
    const lastStart = dayjs(metric.value_at).tz(timezone).startOf(unit)
    const fix = Date.parse(summary.started_at)
    if (fix >= lastStart.add(1, unit).valueOf()) {
        return null
    }
    const starts = values.map((_, index) => lastStart.subtract(values.length - 1 - index, unit).valueOf())
    const factor = bucketTargetFactor(lead, interval)
    return {
        values,
        fixIndex: Math.max(
            0,
            starts.findLastIndex((start) => start <= fix)
        ),
        target:
            factor != null && lead.comparison.operator !== 'between' && lead.comparison.value != null
                ? lead.comparison.value * factor
                : null,
    }
}

export interface MonitoringFigures {
    before: string | null
    sinceFix: string | null
    /** What the two figures are measured over, and the target. */
    basis: string
}

function targetText(lead: MonitoringLeadCheckApi): string {
    const format = { value_format: lead.value_format ?? 'number', unit: lead.unit }
    const { operator, value, bounds } = lead.comparison
    if (operator === 'between' && bounds) {
        return `between ${formatReportMetricValue(format, bounds.lower)} and ${formatReportMetricValue(format, bounds.upper)}`
    }
    return `${operator === 'lte' ? '≤' : '≥'} ${formatReportMetricValue(format, value)}`
}

/**
 * The before and since-fix figures, on a footing the reader can compare: a rate as measured, a count
 * that scales with time as a per-bucket rate, and any other count as its total over its own period.
 */
export function monitoringFigures(
    summary: ReportMonitoringSummaryApi,
    interval: string | null | undefined
): MonitoringFigures | null {
    const lead = summary.lead_check
    if (!lead) {
        return null
    }
    const format = { value_format: lead.value_format ?? 'number', unit: lead.unit }
    const latest = lead.readings.findLast((reading) => reading.observed_value != null) ?? null
    const baselinePeriod = lead.monitoring.baseline_period_minutes ?? null
    const period = monitoringPeriodLabel(lead.monitoring.reference_period_minutes)

    if (isRate(lead)) {
        return {
            before: formatReportMetricValue(format, lead.baseline_value),
            sinceFix: formatReportMetricValue(format, latest?.observed_value),
            basis: `target ${targetText(lead)}`,
        }
    }

    const bucketMinutes = lead.monitoring.threshold_scaling === 'linear' ? BUCKET_MINUTES[interval ?? 'day'] : undefined
    if (bucketMinutes) {
        // A per-bucket rate is rarely a whole number, so it keeps its decimals.
        const rateFormat = { ...format, value_format: format.value_format === 'count' ? 'number' : format.value_format }
        const elapsedMinutes = latest
            ? (Date.parse(latest.measured_at) - Date.parse(summary.started_at)) / 60_000
            : null
        return {
            before:
                lead.baseline_value != null && baselinePeriod
                    ? formatReportMetricValue(rateFormat, (lead.baseline_value * bucketMinutes) / baselinePeriod)
                    : null,
            sinceFix:
                latest?.observed_value != null && elapsedMinutes && elapsedMinutes > 0
                    ? formatReportMetricValue(rateFormat, (latest.observed_value * bucketMinutes) / elapsedMinutes)
                    : null,
            basis: `per ${interval ?? 'day'} · target ${targetText(lead)} in ${period}`,
        }
    }

    return {
        before:
            lead.baseline_value != null
                ? `${formatReportMetricValue(format, lead.baseline_value)}${baselinePeriod ? ` in ${monitoringPeriodLabel(baselinePeriod)}` : ''}`
                : null,
        sinceFix: latest ? `${formatReportMetricValue(format, latest.observed_value)} so far` : null,
        basis: `target ${targetText(lead)} in ${period}`,
    }
}

export const MONITORING_SUMMARY_TAGS: Record<
    MonitoringSummaryStateEnumApi,
    { label: string; type: LemonTagType; description: string }
> = {
    not_on_track: {
        label: 'Not on track',
        type: 'warning',
        description:
            'If this metric fails at the end of the monitoring window, a new report will be opened to research why and attempt a new solution.',
    },
    on_track: {
        label: 'On track',
        type: 'success',
        description: 'This report will be resolved at the end of the monitoring window if the goal is met.',
    },
    awaiting_reading: {
        label: 'Awaiting first reading',
        type: 'muted',
        description: 'A metric check has not been measured yet in this monitoring window.',
    },
    final_check_only: {
        label: 'Checked at window end',
        type: 'muted',
        description: 'No metric is measured during the window. The follow-up checks run when it ends.',
    },
    window_ended: {
        label: 'Verifying',
        type: 'default',
        description: 'The monitoring window has ended. The final checks decide the outcome.',
    },
}
