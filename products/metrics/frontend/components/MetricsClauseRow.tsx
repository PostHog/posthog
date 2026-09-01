import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconEllipsis } from '@posthog/icons'
import {
    LemonButton,
    LemonDropdown,
    LemonInputSelect,
    LemonMenu,
    LemonSelect,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { FilterLogicalOperator, UniversalFiltersGroup, UniversalFiltersGroupValue } from '~/types'

import { MetricNameFilter } from './MetricNameFilter'
import {
    MAX_CLAUSES,
    METRIC_FILTER_OPERATOR_ALLOWLIST,
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

    const recommendedAggregation = clause.selectedMetricType
        ? RECOMMENDED_AGGREGATION_BY_TYPE[clause.selectedMetricType]
        : undefined

    return (
        // Clicking anywhere in the row focuses it; the dropdown overlays render in
        // portals, so picks inside them don't re-trigger this with a stale index.
        <div className="flex flex-wrap items-start gap-2" onClick={select} data-attr="metrics-clause-row">
            {showAlias && (
                <span className="flex items-center h-8">
                    <Tooltip
                        title={
                            isActive
                                ? 'Samples and related links follow this series'
                                : 'Click to focus this series. Samples and related links follow it.'
                        }
                    >
                        <LemonTag
                            type={isActive ? 'primary' : 'muted'}
                            className="cursor-pointer font-mono"
                            onClick={select}
                            data-attr="metrics-clause-alias"
                        >
                            {clause.name}
                        </LemonTag>
                    </Tooltip>
                </span>
            )}
            <div className="flex flex-col gap-1">
                <MetricNameFilter
                    value={clause.metricName}
                    onChange={(name) => {
                        select()
                        setMetricName(name)
                    }}
                    disabled={!!disabledReason}
                    disabledReason={disabledReason}
                />
                {clause.selectedMetricType &&
                    recommendedAggregation &&
                    clause.aggregation !== recommendedAggregation && (
                        <span className="text-xs text-secondary">
                            {clause.selectedMetricType} — {recommendedAggregation} recommended
                        </span>
                    )}
            </div>
            <LemonSelect
                size="small"
                value={clause.aggregation}
                options={AGGREGATION_OPTIONS}
                onChange={(value) => {
                    select()
                    setAggregation(value as MetricAggregation)
                }}
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
                        select()
                        setFilterGroup({ type: FilterLogicalOperator.And, values: [group] })
                    }
                }}
            >
                <MetricsClauseFilterBar disabledReason={disabledReason} />
            </UniversalFilters>
            <MetricsGroupByButton
                groupByKeys={clause.groupByKeys}
                onChange={(keys) => {
                    select()
                    setGroupByKeys(keys)
                }}
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

// Filter chips + "Add filter" button, mirroring the logs viewer's applied-filters row: picking an
// attribute opens the chip for value selection, with suggestions fed by the metrics attribute endpoints.
const MetricsClauseFilterBar = ({ disabledReason }: { disabledReason: string | null }): JSX.Element => {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)
    const [allowInitiallyOpen, setAllowInitiallyOpen] = useState<boolean>(false)

    useOnMountEffect(() => setAllowInitiallyOpen(true))

    return (
        <div className="flex flex-wrap items-center gap-1">
            {filterGroup.values.map((filterOrGroup: UniversalFiltersGroupValue, index: number) =>
                // This UI only ever adds leaf filters, so nested groups can't occur here.
                isUniversalGroupFilterLike(filterOrGroup) ? null : (
                    <span
                        key={index}
                        title={disabledReason ?? undefined}
                        className={disabledReason ? 'pointer-events-none opacity-50' : undefined}
                    >
                        <UniversalFilters.Value
                            index={index}
                            filter={filterOrGroup}
                            onRemove={disabledReason ? undefined : () => removeGroupValue(index)}
                            onChange={(value) => {
                                if (!disabledReason) {
                                    replaceGroupValue(index, value)
                                }
                            }}
                            initiallyOpen={allowInitiallyOpen && !disabledReason}
                            operatorAllowlist={METRIC_FILTER_OPERATOR_ALLOWLIST}
                        />
                    </span>
                )
            )}
            <UniversalFilters.AddFilterButton
                size="small"
                type="secondary"
                title="Filter"
                disabledReason={disabledReason}
            />
        </div>
    )
}

// Group by is a button that opens the attribute multiselect, so the filter bar stays the
// primary control (mirrors how logs and traces keep grouping as a button, not the main bar).
const MetricsGroupByButton = ({
    groupByKeys,
    onChange,
    disabledReason,
}: {
    groupByKeys: string[]
    onChange: (groupByKeys: string[]) => void
    disabledReason: string | null
}): JSX.Element => {
    const { attributeKeyOptions, attributeKeyOptionsLoading } = useValues(metricsViewerLogic)
    const { setGroupBySearch, loadAttributeKeyOptions } = useActions(metricsViewerLogic)
    const [open, setOpen] = useState<boolean>(false)

    const label =
        groupByKeys.length === 0
            ? 'Group by'
            : groupByKeys.length === 1
              ? `Group by: ${groupByKeys[0]}`
              : `Group by: ${groupByKeys.length} attributes`

    return (
        <LemonDropdown
            visible={open}
            closeOnClickInside={false}
            onClickOutside={() => setOpen(false)}
            overlay={
                <div className="p-1 w-[18rem]">
                    <LemonInputSelect
                        mode="multiple"
                        size="small"
                        allowCustomValues
                        value={groupByKeys}
                        onChange={onChange}
                        options={attributeKeyOptions}
                        loading={attributeKeyOptionsLoading}
                        onInputChange={setGroupBySearch}
                        onFocus={() => loadAttributeKeyOptions({})}
                        placeholder="Group by attribute…"
                        data-attr="metrics-viewer-group-by"
                        disabledReason={disabledReason}
                        autoFocus
                    />
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                active={open || groupByKeys.length > 0}
                sideIcon={<IconChevronDown />}
                onClick={() => {
                    setOpen((wasOpen) => !wasOpen)
                    loadAttributeKeyOptions({})
                }}
                disabledReason={disabledReason ?? undefined}
                data-attr="metrics-viewer-group-by-button"
                // Attribute keys can be long, so cap the trigger rather than let it push the row wide
                truncate
                className="max-w-[16rem]"
                tooltip={groupByKeys.length > 0 ? groupByKeys.join(', ') : undefined}
            >
                {label}
            </LemonButton>
        </LemonDropdown>
    )
}
