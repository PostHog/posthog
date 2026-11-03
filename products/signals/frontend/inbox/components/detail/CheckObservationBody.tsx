import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { formatReportMetricValue } from '../../utils/reportMetrics'
import type { CheckObservationContent } from './artefactTypes'

export function CheckObservationBody({ content }: { content: CheckObservationContent }): JSX.Element {
    const format = { value_format: content.value_format ?? 'number', unit: content.unit ?? null }
    const goalFormat = {
        ...format,
        value_format: format.value_format === 'count' ? ('number' as const) : format.value_format,
    }
    const comparison = content.comparison
    const bounds = comparison?.operator === 'between' ? comparison.bounds : null
    const thresholds = bounds ? [bounds.lower, bounds.upper] : [comparison?.value]
    const needsPrecision =
        content.matches === false &&
        content.observed_value != null &&
        thresholds.some(
            (threshold) =>
                threshold != null &&
                threshold !== content.observed_value &&
                [format, goalFormat].some(
                    (metricFormat) =>
                        formatReportMetricValue(metricFormat, threshold) ===
                        formatReportMetricValue(metricFormat, content.observed_value)
                )
        )
    const precision = needsPrecision ? 'exact' : undefined
    const goal =
        comparison?.operator === 'between' && comparison.bounds
            ? `between ${formatReportMetricValue(goalFormat, comparison.bounds.lower, precision)} and ${formatReportMetricValue(goalFormat, comparison.bounds.upper, precision)}`
            : comparison?.value != null
              ? `${comparison.operator === 'gte' ? 'at least' : 'at most'} ${formatReportMetricValue(goalFormat, comparison.value, precision)}`
              : null
    const value = formatReportMetricValue(format, content.observed_value, precision)
    const remaining =
        content.monitoring_ends_at && content.measured_at
            ? dayjs(content.monitoring_ends_at).diff(dayjs(content.measured_at), 'second')
            : null

    return (
        <div className="flex w-full flex-col items-start gap-1 text-xs">
            {typeof content.matches === 'boolean' && value !== null && goal !== null ? (
                <>
                    <span>
                        Goal “{content.title}” is <strong>{content.matches ? 'on track' : 'not on track'}</strong>.
                    </span>
                    <span>
                        Measured {value} against a goal of {goal}.
                    </span>
                </>
            ) : (
                <span>{content.explanation?.replace(/^Interim measurement:\s*/, '')}</span>
            )}
            {remaining !== null && Number.isFinite(remaining) && remaining >= 0 ? (
                <span className="text-tertiary">
                    {humanFriendlyDuration(remaining, { maxUnits: 2 })} of monitoring remained at this measurement.
                </span>
            ) : null}
        </div>
    )
}
