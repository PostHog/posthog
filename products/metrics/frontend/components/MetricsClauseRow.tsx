import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu, Tooltip } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'

import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { MetricNameFilter } from './MetricNameFilter'
import { MetricsClauseFilterBar } from './MetricsClauseFilterBar'
import { MetricsGroupByButton } from './MetricsGroupByButton'
import { MetricsOperations } from './MetricsOperations'
import { MAX_CLAUSES, MetricsViewerClause, metricsViewerLogic } from './metricsViewerLogic'

/** One query line of the viewer: alias, metric picker, filters, operations, and group-by.
 * Editing any control focuses the row — the samples panel, anomaly badge, and picker
 * scoping follow the focused (active) clause. */
export function MetricsClauseRow({
    clause,
    index,
    isActive,
    showAlias,
    disabledReason,
}: {
    clause: MetricsViewerClause
    index: number
    isActive: boolean
    /** Aliases only mean something once there is more than one series. */
    showAlias: boolean
    disabledReason: string | null
}): JSX.Element {
    const { viewerClauses, attributeEndpointFilters } = useValues(metricsViewerLogic)
    const {
        setActiveClauseIndex,
        setMetricName,
        setAggregation,
        setRangeFunction,
        setFilterGroup,
        setGroupByKeys,
        duplicateClause,
        removeClause,
    } = useActions(metricsViewerLogic)

    // Scoping attribute suggestions to the clause's metric lets the backend prune by metric name.
    const metricName = clause.metricName.trim()
    const clauseEndpointFilters = useMemo(
        () => (metricName ? { ...attributeEndpointFilters, metricName } : attributeEndpointFilters),
        [attributeEndpointFilters, metricName]
    )

    const select = (): void => {
        if (!isActive) {
            setActiveClauseIndex(index)
        }
    }

    // Every control edit both focuses this row and applies its own change.
    const withSelect =
        <T,>(setter: (value: T) => void) =>
        (value: T): void => {
            select()
            setter(value)
        }

    return (
        <div className="flex flex-wrap items-start gap-2" data-attr="metrics-clause-row">
            {showAlias && (
                <Tooltip
                    title={
                        isActive
                            ? 'Samples and related links follow this series'
                            : 'Click to focus this series. Samples and related links follow it.'
                    }
                >
                    <LemonButton
                        size="small"
                        type={isActive ? 'primary' : 'secondary'}
                        onClick={select}
                        className="font-mono"
                        data-attr="metrics-clause-alias"
                    >
                        {clause.name}
                    </LemonButton>
                </Tooltip>
            )}
            <div className="flex items-center gap-1">
                <MetricNameFilter
                    value={clause.metricName}
                    onChange={withSelect(setMetricName)}
                    disabled={!!disabledReason}
                    disabledReason={disabledReason}
                />
            </div>
            <UniversalFilters
                // Keyed by the stable alias — an index key would rebind another row's
                // filter logic when a row above it is removed.
                rootKey={`metrics-viewer-filters-${clause.name}`}
                group={clause.filterGroup.values[0] as UniversalFiltersGroup}
                taxonomicGroupTypes={[TaxonomicFilterGroupType.MetricAttributes]}
                endpointFilters={clauseEndpointFilters}
                onChange={(group) => {
                    if (!disabledReason) {
                        withSelect(setFilterGroup)({ type: FilterLogicalOperator.And, values: [group] })
                    }
                }}
            >
                <MetricsClauseFilterBar disabledReason={disabledReason} />
            </UniversalFilters>
            <MetricsOperations
                clause={clause}
                onRangeFunctionChange={withSelect(setRangeFunction)}
                onAggregationChange={withSelect(setAggregation)}
                disabledReason={disabledReason}
            />
            {clause.aggregation && (
                <MetricsGroupByButton
                    groupByKeys={clause.groupByKeys}
                    onChange={withSelect(setGroupByKeys)}
                    disabledReason={disabledReason}
                />
            )}
            <LemonMenu
                items={[
                    {
                        label: 'Duplicate',
                        onClick: () => duplicateClause(index),
                        disabledReason:
                            viewerClauses.length >= MAX_CLAUSES
                                ? `A query can have at most ${MAX_CLAUSES} series`
                                : undefined,
                    },
                    ...(viewerClauses.length > 1
                        ? [
                              {
                                  label: 'Remove',
                                  status: 'danger' as const,
                                  onClick: () => removeClause(index),
                              },
                          ]
                        : []),
                ]}
            >
                <LemonButton
                    size="small"
                    icon={<IconEllipsis />}
                    tooltip="Series options"
                    disabledReason={disabledReason}
                    data-attr="metrics-clause-row-menu"
                />
            </LemonMenu>
        </div>
    )
}
