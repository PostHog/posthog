import { useEffect, useState } from 'react'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { objectsEqual } from 'lib/utils/objects'

import type { MetricsQueryFilter } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { MetricsClauseFilterBar } from './MetricsClauseFilterBar'
import { filterGroupFromMetricFilters, metricFiltersForGroup } from './metricsViewerLogic'

const toMetricFilters = (group: UniversalFiltersGroup): MetricsQueryFilter[] =>
    metricFiltersForGroup(group) as MetricsQueryFilter[]

/** Dashboard-level metric label matchers, such as `service.name = checkout`, that every metrics tile applies. */
export function DashboardMetricLabelFilter({
    metricFilters,
    onChange,
    disabledReason = null,
}: {
    metricFilters: MetricsQueryFilter[] | null | undefined
    onChange: (metricFilters: MetricsQueryFilter[] | null) => void
    disabledReason?: string | null
}): JSX.Element {
    // A chip that is still being edited has no matcher yet, so the chips are kept here
    // and only complete matchers go to the dashboard filters.
    const [filterGroup, setFilterGroup] = useState(() => filterGroupFromMetricFilters(metricFilters ?? []))

    useEffect(() => {
        if (!objectsEqual(toMetricFilters(filterGroup), metricFilters ?? [])) {
            setFilterGroup(filterGroupFromMetricFilters(metricFilters ?? []))
        }
    }, [metricFilters]) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <UniversalFilters
            rootKey="dashboard-metric-label-filters"
            group={filterGroup.values[0] as UniversalFiltersGroup}
            taxonomicGroupTypes={[TaxonomicFilterGroupType.MetricAttributes]}
            onChange={(group) => {
                if (disabledReason) {
                    return
                }
                const nextGroup: UniversalFiltersGroup = { type: FilterLogicalOperator.And, values: [group] }
                setFilterGroup(nextGroup)
                const nextFilters = toMetricFilters(nextGroup)
                if (!objectsEqual(nextFilters, metricFilters ?? [])) {
                    onChange(nextFilters.length ? nextFilters : null)
                }
            }}
        >
            <MetricsClauseFilterBar disabledReason={disabledReason} addFilterTitle="Metric labels" />
        </UniversalFilters>
    )
}
