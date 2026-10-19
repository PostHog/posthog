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
    const goal =
        comparison?.operator === 'between' && comparison.bounds
            ? `between ${formatReportMetricValue(goalFormat, comparison.bounds.lower)} and ${formatReportMetricValue(goalFormat, comparison.bounds.upper)}`
            : comparison?.value != null
              ? `${comparison.operator === 'gte' ? 'at least' : 'at most'} ${formatReportMetricValue(goalFormat, comparison.value)}`
              : null
    const value = formatReportMetricValue(format, content.observed_value)
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
