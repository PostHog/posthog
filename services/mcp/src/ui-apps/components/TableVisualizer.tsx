import type { ReactElement } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { DataTable, type DataTableProps, Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'

import { ChartHeader } from './ChartHeader'
import { BigNumber, LineChart, type Series } from './charts'
import type { TableVisualizerProps } from './types'
import { formatNumber } from './utils'

const TITLE = 'Query results'

// Query results are truncated client-side; sorting a truncated view would
// mislead, so columns are non-sortable.
const MAX_ROWS = 20

function formatCellValue(value: unknown): string {
    if (value === null || value === undefined) {
        return '-'
    }
    if (typeof value === 'number') {
        return formatNumber(value)
    }
    if (typeof value === 'boolean') {
        return value ? 'true' : 'false'
    }
    if (typeof value === 'object') {
        return JSON.stringify(value)
    }
    return String(value)
}

const DATE_PATTERNS = [
    /^\d{4}-\d{2}-\d{2}/, // 2024-01-15 or 2024-01-15T...
    /^\d{4}\/\d{2}\/\d{2}/, // 2024/01/15
    /^\d{2}\/\d{2}\/\d{4}/, // 01/15/2024
    /^\d{2}-\d{2}-\d{4}/, // 15-01-2024
]

function isTimestampLike(value: unknown): boolean {
    if (typeof value !== 'string') {
        return false
    }

    return DATE_PATTERNS.some((pattern) => pattern.test(value))
}

function isNumeric(value: unknown): boolean {
    return typeof value === 'number' && !isNaN(value)
}

interface DetectedFormat {
    type: 'single-number' | 'time-series' | 'table'
    value?: number | undefined
    label?: string | undefined
    timeColumnIndex?: number | undefined
    valueColumnIndex?: number | undefined
}

function detectResultFormat(columns: string[], rows: unknown[][]): DetectedFormat {
    // Single number: 1 row, 1 column, numeric value
    if (rows.length === 1 && columns.length === 1 && rows[0] && isNumeric(rows[0][0])) {
        return {
            type: 'single-number',
            value: rows[0][0] as number,
            label: columns[0],
        }
    }

    // Time series: 2 columns, one timestamp-like and one numeric, at least 2 rows
    if (columns.length === 2 && rows.length >= 2) {
        const col0IsTimestamp = rows.every((row) => isTimestampLike(row[0]))
        const col1IsNumeric = rows.every((row) => isNumeric(row[1]))

        if (col0IsTimestamp && col1IsNumeric) {
            return {
                type: 'time-series',
                timeColumnIndex: 0,
                valueColumnIndex: 1,
            }
        }

        const col1IsTimestamp = rows.every((row) => isTimestampLike(row[1]))
        const col0IsNumeric = rows.every((row) => isNumeric(row[0]))

        if (col1IsTimestamp && col0IsNumeric) {
            return {
                type: 'time-series',
                timeColumnIndex: 1,
                valueColumnIndex: 0,
            }
        }
    }

    return { type: 'table' }
}

function transformToSeries(
    rows: unknown[][],
    timeIdx: number,
    valueIdx: number,
    valueLabel: string
): { series: Series[]; labels: string[]; maxValue: number } {
    const labels: string[] = []
    let maxValue = 0

    const points = rows.map((row, i) => {
        const label = String(row[timeIdx])
        const value = row[valueIdx] as number
        labels.push(label)
        maxValue = Math.max(maxValue, value)
        return { x: i, y: value, label }
    })

    return {
        series: [{ label: valueLabel, points }],
        labels,
        maxValue: maxValue || 1,
    }
}

export function TableVisualizer({ results }: TableVisualizerProps): ReactElement {
    const columns = results?.columns || []
    const rows = results?.results || []

    const format = detectResultFormat(columns, rows)

    if (format.type === 'single-number' && format.value !== undefined) {
        return (
            <div>
                <ChartHeader title={TITLE} />
                <BigNumber value={format.value} label={format.label} />
            </div>
        )
    }

    if (
        format.type === 'time-series' &&
        format.timeColumnIndex !== undefined &&
        format.valueColumnIndex !== undefined
    ) {
        const valueLabel = columns[format.valueColumnIndex] || 'Value'
        const { series, labels, maxValue } = transformToSeries(
            rows,
            format.timeColumnIndex,
            format.valueColumnIndex,
            valueLabel
        )
        return (
            <div>
                <ChartHeader title={TITLE} />
                <LineChart series={series} labels={labels} maxValue={maxValue} showLegend={false} />
            </div>
        )
    }

    if (rows.length === 0) {
        return (
            <div>
                <ChartHeader title={TITLE} />
                <Empty>
                    <EmptyHeader>
                        <EmptyMedia>{emptyStateIllustration('table')}</EmptyMedia>
                        <EmptyDescription>
                            {columns.length === 0 ? 'No rows to display' : 'Query returned no rows'}
                        </EmptyDescription>
                    </EmptyHeader>
                </Empty>
            </div>
        )
    }

    const displayRows = rows.slice(0, MAX_ROWS)
    const hasMore = displayRows.length < rows.length
    const tableColumns: DataTableProps<unknown[], unknown>['columns'] = columns.map((col, colIndex) => ({
        id: String(colIndex),
        header: col,
        accessorFn: (row: unknown[]) => row[colIndex],
        enableSorting: false,
        cell: (info: { getValue: () => unknown }) => formatCellValue(info.getValue()),
    }))

    return (
        <div className="flex flex-col gap-2">
            <ChartHeader title={TITLE} />
            <DataTable columns={tableColumns} data={displayRows} />
            {hasMore && (
                <span className="text-center text-xs text-muted-foreground">
                    Showing {displayRows.length} of {rows.length}+ rows
                </span>
            )}
        </div>
    )
}
