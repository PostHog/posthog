import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInputSelect, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { MetricNameFilter } from './MetricNameFilter'
import { metricNamePickerLogic } from './metricNamePickerLogic'
import {
    clauseLabel,
    MetricAggregation,
    metricsViewerLogic,
    RECOMMENDED_AGGREGATION_BY_TYPE,
} from './metricsViewerLogic'

export const AGGREGATION_OPTIONS: { value: MetricAggregation; label: string }[] = [
    { value: 'sum', label: 'Sum' },
    { value: 'avg', label: 'Average' },
    { value: 'count', label: 'Count' },
    { value: 'p95', label: 'p95' },
    { value: 'rate', label: 'Rate (/s)' },
    { value: 'increase', label: 'Increase' },
]

export function MetricsClauseRow({ index }: { index: number }): JSX.Element | null {
    const { clauses } = useValues(metricsViewerLogic)
    const { updateClause, removeClause } = useActions(metricsViewerLogic)
    const { items: pickerItems } = useValues(metricNamePickerLogic)

    const clause = clauses[index]
    if (!clause) {
        return null
    }
    const multiClause = clauses.length > 1
    const selectedMetricType = pickerItems.find((item) => item.name === clause.metricName)?.metric_type
    const recommendedAggregation = selectedMetricType ? RECOMMENDED_AGGREGATION_BY_TYPE[selectedMetricType] : undefined

    return (
        <div className="flex flex-wrap items-end gap-2">
            {multiClause && (
                <LemonTag type="muted" className="mb-1.5 font-mono">
                    {clauseLabel(index)}
                </LemonTag>
            )}
            <div className="flex flex-col gap-1">
                <MetricNameFilter
                    value={clause.metricName}
                    onChange={(metricName) => updateClause(index, { metricName })}
                />
                {selectedMetricType && recommendedAggregation && clause.aggregation !== recommendedAggregation && (
                    <span className="text-xs text-secondary">
                        {selectedMetricType} — {recommendedAggregation} recommended
                    </span>
                )}
            </div>
            <LemonSelect
                size="small"
                value={clause.aggregation}
                options={AGGREGATION_OPTIONS}
                onChange={(value) => updateClause(index, { aggregation: value as MetricAggregation })}
            />
            <LemonInputSelect
                mode="multiple"
                size="small"
                allowCustomValues
                value={clause.groupByKeys}
                onChange={(groupByKeys) => updateClause(index, { groupByKeys })}
                options={[]}
                placeholder="Group by attribute…"
                className="min-w-[12rem]"
            />
            <LemonInputSelect
                mode="multiple"
                size="small"
                allowCustomValues
                value={clause.filterStrings}
                onChange={(filterStrings) => updateClause(index, { filterStrings })}
                options={[]}
                placeholder="Filter attribute=value…"
                className="min-w-[14rem]"
            />
            {multiClause && (
                <LemonButton
                    size="small"
                    icon={<IconTrash />}
                    onClick={() => removeClause(index)}
                    tooltip="Remove metric"
                />
            )}
        </div>
    )
}
