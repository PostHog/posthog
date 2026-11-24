import { useActions, useValues } from 'kea'
import { CSSProperties } from 'react'

import { SkeletonText, Table, TableBody, TableCell, TableEmpty, TableHeader, TableRow, cn } from '@posthog/quill'

import { insightLogic } from 'scenes/insights/insightLogic'
import { getResultSeries } from 'scenes/insights/utils/resultSeries'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

import type { InsightsTableProps } from './InsightsTable'
import { insightsTableDataLogic } from './insightsTableDataLogic'
import { QuillInsightsTableCell, QuillInsightsTableCellContext } from './QuillInsightsTableCell'
import { QuillInsightsTableHead } from './QuillInsightsTableHead'
import { useInsightsTableModel } from './useInsightsTableModel'
import { useInsightsTableSorting } from './useInsightsTableSorting'
import { useStickyColumnOffsets } from './useStickyColumnOffsets'

const LOADING_ROWS = 3
const EDITOR_ACCESS_REASON = 'You need editor access to modify this insight.'

type QuillInsightsTableProps = Omit<InsightsTableProps, 'isMainInsightView'>

/** The insights table below the chart, in quill. The swatch in the first column links each row to its line. */
export function QuillInsightsTable({
    filterKey,
    isLegend = false,
    embedded = false,
    canEditSeriesNameInline = false,
    seriesNameTooltip,
    canCheckUncheckSeries = true,
    editMode,
    emptyState = 'No insight results',
}: QuillInsightsTableProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const {
        insightDataLoading,
        isNonTimeSeriesDisplay,
        isStickiness,
        breakdownFilter,
        trendsFilter,
        getTrendsHidden,
        querySource,
        actionNames,
    } = useValues(trendsDataLogic(insightProps))
    const { toggleResultHidden } = useActions(trendsDataLogic(insightProps))
    const {
        aggregation,
        pinnedColumns,
        getPreviousResult,
        getPercentOfTotal,
        showPercentOfDayTotal,
        getPercentOfDayTotal,
    } = useValues(insightsTableDataLogic(insightProps))
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const model = useInsightsTableModel({ filterKey, isLegend, embedded, isMainInsightView: false })
    const [sorting, toggleSorting] = useInsightsTableSorting(!editMode)

    // The swatch sits beside the series name instead of in a column of its own.
    const showSwatch = model.columns.some((column) => column.kind === 'color')
    const columns = model.columns.filter((column) => column.kind !== 'color')
    const { headerRowRef, offsets } = useStickyColumnOffsets(
        pinnedColumns,
        columns.map((column) => column.key)
    )
    const stickyProps = (key: string): { sticky?: 'left'; style?: CSSProperties } =>
        pinnedColumns.includes(key) ? { sticky: 'left', style: { left: offsets[key] ?? 0 } } : {}

    const sortColumn = sorting ? columns.find((column) => column.key === sorting.columnKey) : undefined
    const rows =
        sorting && sortColumn && 'sorter' in sortColumn
            ? model.dataSource.slice().sort((a, b) => sorting.order * sortColumn.sorter(a, b))
            : model.dataSource

    const checkboxDisabledReason = canCheckUncheckSeries ? undefined : EDITOR_ACCESS_REASON
    const cellContext: QuillInsightsTableCellContext = {
        model,
        showSwatch,
        canEditSeriesNameInline,
        seriesNameTooltip,
        checkboxDisabledReason,
        breakdownFilter,
        trendsFilter,
        resultSeries: (item) => getResultSeries(querySource, item, actionNames),
        isHidden: getTrendsHidden,
        toggleResultHidden,
        isNonTimeSeriesDisplay,
        isStickiness,
        aggregation,
        getPercentOfTotal,
        getPreviousResult,
        percentOfDayTotal: showPercentOfDayTotal ? getPercentOfDayTotal : null,
        formatPropertyValueForDisplay,
    }

    return (
        <Table
            size="sm"
            // Sticky cells paint their own background, so they take the card color too.
            className="rounded-lg border bg-card [--quill-table-sticky-bg:var(--card)]"
            data-attr="insights-table-graph"
        >
            <TableHeader>
                <TableRow ref={headerRowRef}>
                    {columns.map((column) => (
                        <QuillInsightsTableHead
                            key={column.key}
                            column={column}
                            model={model}
                            sorting={sorting}
                            onSort={toggleSorting}
                            checkboxDisabledReason={checkboxDisabledReason}
                            {...stickyProps(column.key)}
                        />
                    ))}
                </TableRow>
            </TableHeader>
            {rows.length === 0 && !insightDataLoading ? (
                <TableEmpty>{emptyState}</TableEmpty>
            ) : (
                <TableBody
                    aria-busy={insightDataLoading || undefined}
                    className={cn(
                        'transition-opacity motion-reduce:transition-none',
                        insightDataLoading && rows.length > 0 && 'opacity-50'
                    )}
                >
                    {rows.length === 0
                        ? Array.from({ length: LOADING_ROWS }, (_, index) => (
                              <TableRow key={index}>
                                  <TableCell colSpan={columns.length}>
                                      <SkeletonText />
                                  </TableCell>
                              </TableRow>
                          ))
                        : rows.map((item) => (
                              <TableRow key={item.id}>
                                  {columns.map((column) => (
                                      <QuillInsightsTableCell
                                          key={column.key}
                                          column={column}
                                          item={item}
                                          context={cellContext}
                                          {...stickyProps(column.key)}
                                      />
                                  ))}
                              </TableRow>
                          ))}
                </TableBody>
            )}
        </Table>
    )
}
