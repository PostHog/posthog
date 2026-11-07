import { dayjs } from 'lib/dayjs'

import { formatReportMetricValue } from '../../utils/reportMetrics'
import type { CheckObservationContent } from './artefactTypes'

export interface CheckObservationView {
    /** The goal comparison, when the measurement carries one. Absent, the explanation stands in. */
    verdict: { matches: boolean; value: string; goal: string } | null
    explanation: string | undefined
    /** Seconds of monitoring left at this measurement, when known and not negative. */
    remainingSeconds: number | null
}

/** What an interim measurement says, shared by `CheckObservationBody` and its quill sibling. */
export function describeCheckObservation(content: CheckObservationContent): CheckObservationView {
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

    return {
        verdict:
            typeof content.matches === 'boolean' && value !== null && goal !== null
                ? { matches: content.matches, value, goal }
                : null,
        explanation: content.explanation?.replace(/^Interim measurement:\s*/, ''),
        remainingSeconds: remaining !== null && Number.isFinite(remaining) && remaining >= 0 ? remaining : null,
    }
}
