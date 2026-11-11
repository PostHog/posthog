import { useValues } from 'kea'
import { compare as compareFn } from 'natural-orderby'
import { ReactNode, useCallback, useMemo, useState } from 'react'

import { formatAggregationAxisValue } from 'lib/insights/aggregationAxisFormat'
import { COUNTRY_CODE_TO_LONG_NAME } from 'lib/utils/country'
import { entityFilterLogic } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { getResultSeries, getResultSeriesIndex } from 'scenes/insights/utils/resultSeries'
import { teamLogic } from 'scenes/teamLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { extractDisplayLabel } from '~/queries/nodes/DataTable/utils'
import { hasBreakdownFilter } from '~/queries/schema/node-guards'
import { ChartDisplayType, TrendsFilterType } from '~/types'

import { getResultSeriesName } from 'products/product_analytics/frontend/insights/shared/resultSeriesName'
import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'
import { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

import { getAggregatedValue, insightsTableDataLogic } from './insightsTableDataLogic'

export type CalcColumnState = 'total' | 'average' | 'median'

export const MAX_VALUE_COLUMNS = 100

type Sorter = (a: IndexedTrendResult, b: IndexedTrendResult) => number

/** One column of the insights table. The Lemon and quill tables render the same list, so they show and sort alike. */
export type InsightsTableColumn =
    | { kind: 'label'; key: 'label'; sorter: Sorter }
    | { kind: 'breakdown'; key: 'breakdown'; sorter: Sorter }
    | {
          kind: 'multiple-breakdown'
          key: string
          title: string
          formatLabel: (item: IndexedTrendResult) => string
          sorter: Sorter
      }
    | { kind: 'world-map'; key: 'breakdown_addendum'; sorter: Sorter }
    | { kind: 'color'; key: 'color' }
    | { kind: 'aggregation'; key: 'count'; sorter: Sorter }
    | { kind: 'percent-of-total'; key: 'percent-of-total'; sorter: Sorter }
    | { kind: 'previous'; key: 'previous'; sorter: Sorter }
    | { kind: 'value'; key: string; index: number; sorter: Sorter }
    | { kind: 'load-more'; key: 'load-more-columns'; hiddenCount: number }

const NUMERIC_COLUMN_KINDS: InsightsTableColumn['kind'][] = ['aggregation', 'percent-of-total', 'previous', 'value']

export function isNumericColumn(column: InsightsTableColumn): boolean {
    return NUMERIC_COLUMN_KINDS.includes(column.kind)
}

export interface InsightsTableModelProps {
    filterKey: string
    isLegend: boolean
    embedded: boolean
    isMainInsightView: boolean
}

export interface InsightsTableModel {
    columns: InsightsTableColumn[]
    dataSource: IndexedTrendResult[]
    hasCheckboxes: boolean
    isSingleSeriesWithBreakdown: boolean
    isCompareTable: boolean
    /** Set when the insight has a breakdown. */
    formatItemBreakdownLabel?: (item: IndexedTrendResult) => string
    showCountedByTag: boolean
    mathPropertyOf: (item: IndexedTrendResult) => string | null | undefined
    handleSeriesEditClick: (item: IndexedTrendResult) => void
    renderCount: (value: number) => ReactNode
    showMoreColumns: () => void
}

export function useInsightsTableModel({
    filterKey,
    isLegend,
    embedded,
    isMainInsightView,
}: InsightsTableModelProps): InsightsTableModel {
    const { insightProps } = useValues(insightLogic)
    const {
        indexedResults,
        isNonTimeSeriesDisplay,
        compareFilter,
        isTrends,
        isStickiness,
        display,
        breakdownFilter,
        trendsFilter,
        isSingleSeriesDefinition,
        getTrendsHidden,
        querySource,
        actionNames,
    } = useValues(trendsDataLogic(insightProps))
    const { aggregation, allowAggregation, getPreviousResult, displayResults, showPercentOfTotal, getPercentOfTotal } =
        useValues(insightsTableDataLogic(insightProps))
    const { baseCurrency } = useValues(teamLogic)
    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const [maxVisibleColumns, setMaxVisibleColumns] = useState(MAX_VALUE_COLUMNS)

    const isCompareTable = isMainInsightView && !!compareFilter?.compare

    const handleSeriesEditClick = (item: IndexedTrendResult): void => {
        const entityFilter = entityFilterLogic.findMounted({
            typeKey: filterKey,
        })
        if (entityFilter) {
            entityFilter.actions.selectSeriesAt(getResultSeriesIndex(querySource, item) ?? null)
            entityFilter.actions.showModal()
        }
    }

    const mathPropertyOf = (item: IndexedTrendResult): string | null | undefined =>
        getResultSeries(querySource, item).math?.math_property
    const showCountedByTag = indexedResults.some((item) => {
        const math = getResultSeries(querySource, item).math?.math
        return !!math && math !== 'total'
    })

    const hasCheckboxes =
        isLegend &&
        (!display ||
            ![
                ChartDisplayType.BoldNumber,
                ChartDisplayType.WorldMap,
                ChartDisplayType.CalendarHeatmap,
                ChartDisplayType.BoxPlot,
            ].includes(display))

    // When there's only one series definition and a single breakdown, the "Series" column would
    // redundantly show the same event name on every row. Instead, merge the breakdown
    // info into the first column and skip the separate "Breakdown" column.
    const isSingleSeriesWithBreakdown =
        isSingleSeriesDefinition &&
        hasBreakdownFilter(breakdownFilter) &&
        !(breakdownFilter.breakdowns && breakdownFilter.breakdowns.length > 1)

    // Untruncated — BreakdownColumnItem clips for display but needs the full value for hover and copy
    const formatItemBreakdownLabel = hasBreakdownFilter(breakdownFilter)
        ? (item: IndexedTrendResult): string =>
              formatBreakdownLabel(
                  Array.isArray(item.breakdown_value) ? item.breakdown_value[0] : item.breakdown_value,
                  breakdownFilter,
                  allCohorts?.results,
                  formatPropertyValueForDisplay,
                  breakdownFilter.breakdowns ? 0 : undefined,
                  undefined,
                  false
              )
        : undefined

    const columns: InsightsTableColumn[] = []

    columns.push({
        kind: 'label',
        key: 'label',
        sorter: (a, b) => {
            if (isSingleSeriesWithBreakdown) {
                if (typeof a.breakdown_value === 'number' && typeof b.breakdown_value === 'number') {
                    return a.breakdown_value - b.breakdown_value
                }
                return compareFn()(formatItemBreakdownLabel!(a), formatItemBreakdownLabel!(b))
            }

            const labelA = getResultSeriesName(getResultSeries(querySource, a, actionNames)) || a.label || ''
            const labelB = getResultSeriesName(getResultSeries(querySource, b, actionNames)) || b.label || ''
            return labelA.localeCompare(labelB)
        },
    })

    if (hasBreakdownFilter(breakdownFilter) && breakdownFilter.breakdown) {
        if (!isSingleSeriesWithBreakdown) {
            columns.push({
                kind: 'breakdown',
                key: 'breakdown',
                sorter: (a, b) => {
                    if (typeof a.breakdown_value === 'number' && typeof b.breakdown_value === 'number') {
                        return a.breakdown_value - b.breakdown_value
                    }
                    return compareFn()(formatItemBreakdownLabel!(a), formatItemBreakdownLabel!(b))
                },
            })
        }

        if (isTrends && display === ChartDisplayType.WorldMap) {
            columns.push({
                kind: 'world-map',
                key: 'breakdown_addendum',
                sorter: (a, b) => {
                    const labelA = COUNTRY_CODE_TO_LONG_NAME[a.breakdown_value as string] || ''
                    const labelB = COUNTRY_CODE_TO_LONG_NAME[b.breakdown_value as string] || ''
                    return labelA.localeCompare(labelB)
                },
            })
        }
    } else if (breakdownFilter?.breakdowns && !isSingleSeriesWithBreakdown) {
        breakdownFilter.breakdowns.forEach((breakdown, index) => {
            const formatLabel = (item: IndexedTrendResult): string =>
                formatBreakdownLabel(
                    Array.isArray(item.breakdown_value) ? item.breakdown_value[index] : item.breakdown_value,
                    breakdownFilter,
                    allCohorts?.results,
                    formatPropertyValueForDisplay,
                    index,
                    undefined,
                    false
                )

            columns.push({
                kind: 'multiple-breakdown',
                key: `breakdown-${breakdown.property?.toString() || index}`,
                title: extractDisplayLabel(breakdown.property?.toString()),
                formatLabel,
                sorter: (a, b) => {
                    const leftValue = Array.isArray(a.breakdown_value) ? a.breakdown_value[index] : a.breakdown_value
                    const rightValue = Array.isArray(b.breakdown_value) ? b.breakdown_value[index] : b.breakdown_value

                    if (typeof leftValue === 'number' && typeof rightValue === 'number') {
                        return leftValue - rightValue
                    }

                    return compareFn()(formatLabel(a), formatLabel(b))
                },
            })
        })
    }

    // Do not show colors in the table when we display World map.
    // It is a choropleth where colors don't represent categories
    if (!isMainInsightView && !embedded && display !== ChartDisplayType.WorldMap) {
        columns.push({ kind: 'color', key: 'color' })
    }

    if (allowAggregation) {
        columns.push({
            kind: 'aggregation',
            key: 'count',
            sorter: (a, b) =>
                (getAggregatedValue(a, aggregation, isNonTimeSeriesDisplay) ?? 0) -
                (getAggregatedValue(b, aggregation, isNonTimeSeriesDisplay) ?? 0),
        })

        if (showPercentOfTotal) {
            columns.push({
                kind: 'percent-of-total',
                key: 'percent-of-total',
                sorter: (a, b) => (getPercentOfTotal(a) ?? 0) - (getPercentOfTotal(b) ?? 0),
            })
        }

        if (isCompareTable) {
            columns.push({
                kind: 'previous',
                key: 'previous',
                sorter: (a, b) => {
                    const prevA = getPreviousResult(a)
                    const prevB = getPreviousResult(b)
                    const valA = prevA ? (getAggregatedValue(prevA, aggregation, isNonTimeSeriesDisplay) ?? 0) : 0
                    const valB = prevB ? (getAggregatedValue(prevB, aggregation, isNonTimeSeriesDisplay) ?? 0) : 0
                    return valA - valB
                },
            })
        }
    }

    const valueColumns = useMemo((): InsightsTableColumn[] => {
        // Don't show value columns for non-time-series displays like WorldMap and Heatmap
        if (
            display === ChartDisplayType.WorldMap ||
            display === ChartDisplayType.CalendarHeatmap ||
            display === ChartDisplayType.BoxPlot
        ) {
            return []
        }

        const results = indexedResults?.[0]?.data
        if (!results?.length) {
            return []
        }

        const visibleStartIndex = Math.max(0, results.length - maxVisibleColumns)
        return Array.from({ length: results.length - visibleStartIndex }, (_, i) => {
            const index = visibleStartIndex + i
            return {
                kind: 'value',
                key: `data-${index}`,
                index,
                sorter: (a: IndexedTrendResult, b: IndexedTrendResult) => {
                    const aValue = a.data[index] ?? NaN
                    const bValue = b.data[index] ?? NaN
                    return isStickiness ? aValue / a.count - bValue / b.count : aValue - bValue
                },
            }
        })
    }, [indexedResults, display, isStickiness, maxVisibleColumns])

    columns.push(...valueColumns)

    const hiddenColumns = (indexedResults?.[0]?.data?.length ?? 0) - valueColumns.length
    if (hiddenColumns > 0) {
        columns.push({ kind: 'load-more', key: 'load-more-columns', hiddenCount: hiddenColumns })
    }

    const renderCount = useCallback(
        (value: number) => formatAggregationAxisValue(trendsFilter as Partial<TrendsFilterType>, value, baseCurrency),
        [trendsFilter, baseCurrency]
    )

    const dataSource = isMainInsightView
        ? displayResults
        : isLegend
          ? indexedResults
          : indexedResults.filter((dataset) => !getTrendsHidden(dataset))

    return {
        columns,
        dataSource,
        hasCheckboxes,
        isSingleSeriesWithBreakdown,
        isCompareTable,
        formatItemBreakdownLabel,
        showCountedByTag,
        mathPropertyOf,
        handleSeriesEditClick,
        renderCount,
        showMoreColumns: () => setMaxVisibleColumns((prev) => prev + MAX_VALUE_COLUMNS),
    }
}
