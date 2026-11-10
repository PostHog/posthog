import './InsightsTable.scss'

import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { percentage } from 'lib/utils/numbers'
import { insightLogic } from 'scenes/insights/insightLogic'
import { getResultSeries } from 'scenes/insights/utils/resultSeries'
import { teamLogic } from 'scenes/teamLogic'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { extractDisplayLabel } from '~/queries/nodes/DataTable/utils'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'
import { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

import { AggregationColumnItem, AggregationColumnTitle, CALC_COLUMN_LABELS } from './columns/AggregationColumn'
import { BreakdownColumnItem, BreakdownColumnTitle, MultipleBreakdownColumnTitle } from './columns/BreakdownColumn'
import { ColorCustomizationColumnItem, ColorCustomizationColumnTitle } from './columns/ColorCustomizationColumn'
import { SeriesCheckColumnItem, SeriesCheckColumnTitle } from './columns/SeriesCheckColumn'
import { SeriesColumnItem, formatCompareLabel } from './columns/SeriesColumn'
import { ValueColumnItem, ValueColumnTitle } from './columns/ValueColumn'
import { WorldMapColumnItem, WorldMapColumnTitle } from './columns/WorldMapColumn'
import { AggregationType, insightsTableDataLogic } from './insightsTableDataLogic'
import { CalcColumnState, InsightsTableColumn, MAX_VALUE_COLUMNS, useInsightsTableModel } from './useInsightsTableModel'

export interface InsightsTableProps {
    /** Key for the entityFilterLogic */
    filterKey: string
    /**
     * Whether this is just a legend instead of standalone insight viz.
     * @default false
     */
    isLegend?: boolean
    /**
     * Whether this is table is embedded in another card or whether it should be a card of its own.
     * @default false
     */
    embedded?: boolean
    /** @default false */
    canEditSeriesNameInline?: boolean
    seriesNameTooltip?: string
    /**
     * (Un)checking series updates the insight via the API, so it should be disabled if updates aren't desired.
     *  @default true
     */
    canCheckUncheckSeries?: boolean
    /**
     * Whether this table is below another insight or the insight is in table view.
     * @default false
     */
    isMainInsightView?: boolean
    /** Whether the insight is in edit mode. */
    editMode?: boolean
    /** @default 'No insight results' */
    emptyState?: ReactNode
}

export function InsightsTable({
    filterKey,
    isLegend = false,
    embedded = false,
    canEditSeriesNameInline = false,
    seriesNameTooltip,
    canCheckUncheckSeries = true,
    isMainInsightView = false,
    editMode,
    emptyState = 'No insight results',
}: InsightsTableProps): JSX.Element {
    const { insightProps, isInDashboardContext, insight } = useValues(insightLogic)
    const {
        insightDataLoading,
        indexedResults,
        isNonTimeSeriesDisplay,
        compareFilter,
        isStickiness,
        interval,
        breakdownFilter,
        trendsFilter,
        isSingleSeriesDefinition,
        getTrendsColor,
        getTrendsHidden,
        insightData,
        querySource,
        actionNames,
    } = useValues(trendsDataLogic(insightProps))
    const { toggleResultHidden, toggleAllResultsHidden } = useActions(trendsDataLogic(insightProps))
    const {
        aggregation,
        pinnedColumns,
        isColumnPinned,
        getPreviousResult,
        getPercentOfTotal,
        showPercentOfDayTotal,
        getPercentOfDayTotal,
    } = useValues(insightsTableDataLogic(insightProps))
    const { setDetailedResultsAggregationType, toggleColumnPin } = useActions(insightsTableDataLogic(insightProps))
    const { weekStartDay, timezone } = useValues(teamLogic)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const {
        columns: columnModel,
        dataSource,
        hasCheckboxes,
        isSingleSeriesWithBreakdown,
        isCompareTable,
        formatItemBreakdownLabel,
        showCountedByTag,
        mathPropertyOf,
        handleSeriesEditClick,
        renderCount,
        showMoreColumns,
    } = useInsightsTableModel({ filterKey, isLegend, embedded, isMainInsightView })

    const toLemonColumn = (column: InsightsTableColumn): LemonTableColumn<IndexedTrendResult, any> => {
        switch (column.kind) {
            case 'label':
                return {
                    title: (
                        <div className="flex items-center gap-4 min-w-0">
                            {hasCheckboxes && (
                                <SeriesCheckColumnTitle
                                    indexedResults={indexedResults}
                                    canCheckUncheckSeries={canCheckUncheckSeries}
                                    getTrendsHidden={getTrendsHidden}
                                    toggleAllResultsHidden={toggleAllResultsHidden}
                                    disabledReason={
                                        !canCheckUncheckSeries
                                            ? 'You need editor access to modify this insight.'
                                            : undefined
                                    }
                                />
                            )}
                            {isSingleSeriesWithBreakdown ? (
                                breakdownFilter?.breakdown ? (
                                    <BreakdownColumnTitle breakdownFilter={breakdownFilter} />
                                ) : (
                                    <MultipleBreakdownColumnTitle>
                                        {extractDisplayLabel(
                                            breakdownFilter?.breakdowns?.[0]?.property?.toString() ?? ''
                                        )}
                                    </MultipleBreakdownColumnTitle>
                                )
                            ) : (
                                <span>Series</span>
                            )}
                        </div>
                    ),
                    render: (_, item) => {
                        const label = isSingleSeriesWithBreakdown ? (
                            <BreakdownColumnItem
                                item={item}
                                formatItemBreakdownLabel={formatItemBreakdownLabel!}
                                breakdownFilter={breakdownFilter ?? undefined}
                                compareValue={
                                    // Formula results synthesized from filler rows can carry compare_label without compare
                                    (item.compare || item.compare_label) && !isCompareTable
                                        ? formatCompareLabel(item)
                                        : undefined
                                }
                            />
                        ) : (
                            <SeriesColumnItem
                                item={item}
                                series={getResultSeries(querySource, item, actionNames)}
                                showCountedByTag={showCountedByTag}
                                canEditSeriesNameInline={canEditSeriesNameInline}
                                seriesNameTooltip={seriesNameTooltip}
                                handleEditClick={handleSeriesEditClick}
                                hasMultipleSeries={!isSingleSeriesDefinition}
                                hasBreakdown={!!formatItemBreakdownLabel}
                                hideCompare={isCompareTable}
                            />
                        )

                        return hasCheckboxes ? (
                            <SeriesCheckColumnItem
                                item={item}
                                canCheckUncheckSeries={canCheckUncheckSeries}
                                isHidden={getTrendsHidden(item)}
                                toggleResultHidden={toggleResultHidden}
                                label={<div className="ml-2 font-normal">{label}</div>}
                                disabledReason={
                                    !canCheckUncheckSeries
                                        ? 'You need editor access to modify this insight.'
                                        : undefined
                                }
                            />
                        ) : (
                            label
                        )
                    },
                    key: column.key,
                    sorter: column.sorter,
                }
            case 'breakdown':
                return {
                    title: breakdownFilter ? (
                        <BreakdownColumnTitle
                            breakdownFilter={breakdownFilter ?? undefined}
                            isPinned={isColumnPinned(column.key)}
                            onTogglePin={() => toggleColumnPin(column.key)}
                        />
                    ) : null,
                    render: (_, item) => (
                        <BreakdownColumnItem
                            item={item}
                            formatItemBreakdownLabel={formatItemBreakdownLabel!}
                            breakdownFilter={breakdownFilter ?? undefined}
                        />
                    ),
                    key: column.key,
                    sorter: column.sorter,
                }
            case 'world-map':
                return {
                    title: <WorldMapColumnTitle />,
                    render: (_, item: IndexedTrendResult) => <WorldMapColumnItem item={item} />,
                    key: column.key,
                    sorter: column.sorter,
                }
            case 'multiple-breakdown':
                return {
                    title: (
                        <MultipleBreakdownColumnTitle
                            isPinned={isColumnPinned(column.key)}
                            onTogglePin={() => toggleColumnPin(column.key)}
                        >
                            {column.title}
                        </MultipleBreakdownColumnTitle>
                    ),
                    render: (_, item) => (
                        <BreakdownColumnItem
                            item={item}
                            formatItemBreakdownLabel={column.formatLabel}
                            breakdownFilter={breakdownFilter ?? undefined}
                        />
                    ),
                    key: column.key,
                    sorter: column.sorter,
                }
            case 'color':
                return {
                    title: <ColorCustomizationColumnTitle />,
                    render: (_, item) => <ColorCustomizationColumnItem item={item} />,
                    key: column.key,
                }
            case 'aggregation':
                return {
                    title: (
                        <AggregationColumnTitle
                            isNonTimeSeriesDisplay={isNonTimeSeriesDisplay}
                            aggregation={aggregation}
                            setAggregationType={(state: CalcColumnState) =>
                                setDetailedResultsAggregationType(state as AggregationType)
                            }
                        />
                    ),
                    render: (_: any, item: IndexedTrendResult) => (
                        <AggregationColumnItem
                            item={item}
                            mathProperty={mathPropertyOf(item)}
                            isNonTimeSeriesDisplay={isNonTimeSeriesDisplay}
                            aggregation={aggregation}
                            trendsFilter={trendsFilter}
                        />
                    ),
                    sorter: column.sorter,
                    dataIndex: column.key,
                    align: 'right',
                }
            case 'percent-of-total':
                return {
                    title: <span>% of total</span>,
                    render: (_: any, item: IndexedTrendResult) => {
                        const share = getPercentOfTotal(item)
                        return <span>{share === null ? '—' : percentage(share, 1)}</span>
                    },
                    sorter: column.sorter,
                    key: column.key,
                    align: 'right',
                }
            case 'previous':
                return {
                    title: <span>Previous {CALC_COLUMN_LABELS[aggregation]}</span>,
                    render: (_: any, item: IndexedTrendResult) => {
                        const previousItem = getPreviousResult(item)
                        if (!previousItem) {
                            return <span>—</span>
                        }
                        return (
                            <AggregationColumnItem
                                item={previousItem}
                                mathProperty={mathPropertyOf(previousItem)}
                                isNonTimeSeriesDisplay={isNonTimeSeriesDisplay}
                                aggregation={aggregation}
                                trendsFilter={trendsFilter}
                            />
                        )
                    },
                    sorter: column.sorter,
                    key: column.key,
                    align: 'right',
                }
            case 'value':
                return {
                    title: isStickiness ? (
                        `${interval ? interval.charAt(0).toUpperCase() + interval.slice(1) : 'Day'} ${column.index + 1}`
                    ) : (
                        <ValueColumnTitle
                            index={column.index}
                            indexedResults={indexedResults}
                            compare={compareFilter?.compare}
                            interval={interval}
                            resolvedDateRange={insightData?.resolved_date_range}
                            timezone={timezone}
                            weekStartDay={weekStartDay}
                        />
                    ),
                    render: (_, item: IndexedTrendResult) => (
                        <ValueColumnItem
                            index={column.index}
                            item={item}
                            mathProperty={mathPropertyOf(item)}
                            isStickiness={isStickiness}
                            renderCount={renderCount}
                            formatPropertyValueForDisplay={formatPropertyValueForDisplay}
                            percentOfDayTotal={showPercentOfDayTotal ? getPercentOfDayTotal(item, column.index) : null}
                        />
                    ),
                    key: column.key,
                    sorter: column.sorter,
                    align: 'right',
                }
            case 'load-more':
                return {
                    title: (
                        <LemonButton type="secondary" size="xsmall" onClick={showMoreColumns}>
                            +{Math.min(column.hiddenCount, MAX_VALUE_COLUMNS).toLocaleString()} columns
                        </LemonButton>
                    ),
                    render: () => null,
                    key: column.key,
                }
        }
    }

    return (
        <LemonTable
            id={isInDashboardContext ? insight.short_id : undefined}
            dataSource={dataSource}
            embedded={embedded}
            columns={columnModel.map(toLemonColumn)}
            rowKey="id"
            loading={insightDataLoading}
            disableTableWhileLoading={false}
            emptyState={emptyState}
            data-attr="insights-table-graph"
            useURLForSorting={!editMode}
            rowRibbonColor={
                isLegend
                    ? (item) => {
                          const isPrevious = !!item.compare && item.compare_label === 'previous'

                          const themeColor = getTrendsColor(item)
                          const mainColor = isPrevious ? `${themeColor}80` : themeColor

                          return mainColor
                      }
                    : undefined
            }
            firstColumnSticky
            pinnedColumns={pinnedColumns}
            maxHeaderWidth="20rem"
            // Allow vertical scrolling so long tables inside constrained
            // containers (dashboards, embedded views) remain scrollable.
            allowContentScroll={isInDashboardContext || embedded}
        />
    )
}
