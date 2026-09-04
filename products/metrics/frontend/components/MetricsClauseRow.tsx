import { useActions, useValues } from 'kea'

import { IconEllipsis, IconInfo } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSelect, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'

import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { metricsSceneLogic } from '../metricsSceneLogic'
import { MetricNameFilter } from './MetricNameFilter'
import { MetricsClauseFilterBar } from './MetricsClauseFilterBar'
import { MetricsGroupByButton } from './MetricsGroupByButton'
import { metricsFundamentalsLogic } from './metricsFundamentalsLogic'
import {
    MAX_CLAUSES,
    MetricAggregation,
    MetricsViewerClause,
    RECOMMENDED_AGGREGATION_BY_TYPE,
    metricsViewerLogic,
} from './metricsViewerLogic'

const AGGREGATION_OPTIONS: { value: MetricAggregation; label: string }[] = [
    { value: 'sum', label: 'Sum' },
    { value: 'avg', label: 'Average' },
    { value: 'count', label: 'Series count' },
    { value: 'min', label: 'Min' },
    { value: 'max', label: 'Max' },
    { value: 'p95', label: 'p95' },
    { value: 'rate', label: 'Rate (/s)' },
    { value: 'increase', label: 'Increase' },
]

/** One query line of the viewer: alias, metric picker, aggregation, filters, and group-by.
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
        setFilterGroup,
        setGroupByKeys,
        duplicateClause,
        removeClause,
    } = useActions(metricsViewerLogic)

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

    const recommendedAggregation = clause.selectedMetricType
        ? RECOMMENDED_AGGREGATION_BY_TYPE[clause.selectedMetricType]
        : undefined
    const { setActiveTab } = useActions(metricsSceneLogic)
    const { explainMetric } = useActions(metricsFundamentalsLogic)

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
            <div className="flex flex-col gap-1">
                <div className="flex items-center gap-1">
                    <MetricNameFilter
                        value={clause.metricName}
                        onChange={withSelect(setMetricName)}
                        disabled={!!disabledReason}
                        disabledReason={disabledReason}
                    />
                    {clause.metricName && clause.selectedMetricType && (
                        <Tooltip title="Take this metric apart: see how its chart value is recomputed from raw samples.">
                            <LemonButton
                                size="small"
                                type="tertiary"
                                icon={<IconInfo />}
                                onClick={() => {
                                    explainMetric({
                                        metricName: clause.metricName,
                                        aggregation: clause.aggregation,
                                    })
                                    setActiveTab('fundamentals')
                                }}
                                data-attr="metrics-clause-explain"
                            />
                        </Tooltip>
                    )}
                </div>
                {clause.selectedMetricType &&
                    recommendedAggregation &&
                    (clause.aggregation !== recommendedAggregation ? (
                        <span className="text-xs text-secondary">
                            {clause.selectedMetricType}: {recommendedAggregation} recommended
                        </span>
                    ) : (
                        <LemonTag type="muted" size="small" className="self-start">
                            {clause.selectedMetricType} · {recommendedAggregation}
                        </LemonTag>
                    ))}
            </div>
            <LemonSelect
                size="small"
                value={clause.aggregation}
                options={AGGREGATION_OPTIONS}
                onChange={withSelect(setAggregation)}
                data-attr="metrics-viewer-aggregation"
                disabledReason={disabledReason}
            />
            <UniversalFilters
                // Keyed by the stable alias — an index key would rebind another row's
                // filter logic when a row above it is removed.
                rootKey={`metrics-viewer-filters-${clause.name}`}
                group={clause.filterGroup.values[0] as UniversalFiltersGroup}
                taxonomicGroupTypes={[TaxonomicFilterGroupType.MetricAttributes]}
                endpointFilters={attributeEndpointFilters}
                onChange={(group) => {
                    if (!disabledReason) {
                        withSelect(setFilterGroup)({ type: FilterLogicalOperator.And, values: [group] })
                    }
                }}
            >
                <MetricsClauseFilterBar disabledReason={disabledReason} />
            </UniversalFilters>
            <MetricsGroupByButton
                groupByKeys={clause.groupByKeys}
                onChange={withSelect(setGroupByKeys)}
                disabledReason={disabledReason}
            />
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
