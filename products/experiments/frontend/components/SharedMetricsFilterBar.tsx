import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { MemberMultiSelect } from 'lib/components/MemberMultiSelect'
import { TagSelect } from 'lib/components/TagSelect'
import { sharedMetricsLogic } from 'scenes/experiments/SharedMetrics/sharedMetricsLogic'

import { ExperimentSavedMetricsListMetricType } from '../generated/api.schemas'

const METRIC_TYPE_OPTIONS: { label: string; value: ExperimentSavedMetricsListMetricType | null }[] = [
    { label: 'Any type', value: null },
    { label: 'Mean', value: ExperimentSavedMetricsListMetricType.Mean },
    { label: 'Funnel', value: ExperimentSavedMetricsListMetricType.Funnel },
    { label: 'Ratio', value: ExperimentSavedMetricsListMetricType.Ratio },
    { label: 'Retention', value: ExperimentSavedMetricsListMetricType.Retention },
    { label: 'Percentile', value: ExperimentSavedMetricsListMetricType.Quantile },
    { label: 'Trend', value: ExperimentSavedMetricsListMetricType.Trend },
]

export function SharedMetricsFilterBar(): JSX.Element {
    const { filters } = useValues(sharedMetricsLogic)
    const { setFilters } = useActions(sharedMetricsLogic)

    return (
        <>
            <div className="flex items-center gap-2">
                <b>Created by</b>
                <MemberMultiSelect
                    defaultLabel="Any user"
                    value={filters.created_by_id ?? []}
                    size="xsmall"
                    onChange={(userIds) => setFilters({ created_by_id: userIds.length ? userIds : undefined })}
                />
            </div>
            <div className="flex items-center gap-2">
                <b>Tags</b>
                <TagSelect
                    defaultLabel="Any tags"
                    value={filters.tags ?? []}
                    size="xsmall"
                    onChange={(tags) => setFilters({ tags: tags.length ? tags : undefined })}
                    data-attr="shared-metrics-select-tags"
                />
            </div>
            <div className="flex items-center gap-2">
                <b>Type</b>
                <LemonSelect
                    size="xsmall"
                    options={METRIC_TYPE_OPTIONS}
                    value={filters.metric_type ?? null}
                    onChange={(metricType) => setFilters({ metric_type: metricType ?? undefined })}
                    dropdownMatchSelectWidth={false}
                    data-attr="shared-metrics-select-type"
                />
            </div>
        </>
    )
}
