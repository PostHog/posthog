import type { ReactElement } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { DataTable, type DataTableProps, Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'

import { ChartHeader } from './ChartHeader'
import type { PathsVisualizerProps } from './types'
import { formatDuration, formatNumber } from './utils'

const TITLE = 'Paths'

// Edges are sorted by user count and the busiest paths lead, so a truncated
// view stays meaningful; columns are non-sortable to match.
const MAX_ROWS = 20

function formatCellValue(value: unknown): string {
    if (value === null || value === undefined) {
        return '-'
    }
    if (typeof value === 'number') {
        return formatNumber(value)
    }
    return String(value)
}

/** Node keys are `<stepIndex>_<value>`; split into the step number and the path/value. */
function parseNode(key: string): { step: number; path: string } {
    const sep = key.indexOf('_')
    if (sep === -1) {
        return { step: 0, path: key }
    }
    const step = Number.parseInt(key.slice(0, sep), 10)
    return { step: Number.isNaN(step) ? 0 : step, path: key.slice(sep + 1) }
}

export function PathsVisualizer({ results }: PathsVisualizerProps): ReactElement {
    const edges = Array.isArray(results) ? results : []

    if (edges.length === 0) {
        return (
            <div>
                <ChartHeader title={TITLE} />
                <Empty>
                    <EmptyHeader>
                        <EmptyMedia>{emptyStateIllustration('generic')}</EmptyMedia>
                        <EmptyDescription>No path data available</EmptyDescription>
                    </EmptyHeader>
                </Empty>
            </div>
        )
    }

    // Each row is an edge between two nodes; sort by user count so the busiest paths lead.
    const sorted = [...edges].sort((a, b) => (b.value ?? 0) - (a.value ?? 0))

    const columns = ['Step', 'From', 'To', 'Users', 'Avg. time']
    const rows: unknown[][] = sorted.map((edge) => {
        const from = parseNode(edge.source)
        const to = parseNode(edge.target)
        return [
            `${from.step} → ${to.step}`,
            from.path,
            to.path,
            edge.value ?? 0,
            edge.average_conversion_time != null ? formatDuration(edge.average_conversion_time) : '-',
        ]
    })

    const displayRows = rows.slice(0, MAX_ROWS)
    const hasMore = displayRows.length < rows.length
    const tableColumns: DataTableProps<unknown[], unknown>['columns'] = columns.map((col, colIndex) => ({
        id: String(colIndex),
        header: col,
        accessorFn: (row: unknown[]) => row[colIndex],
        enableSorting: false,
        cell: (info: { getValue: () => unknown }) => formatCellValue(info.getValue()),
    }))

    const topUsers = sorted[0]?.value ?? 0

    return (
        <div>
            <ChartHeader title={TITLE} />
            <DataTable columns={tableColumns} data={displayRows} className="rounded-lg border" />
            {hasMore && (
                <span className="mt-2 block text-center text-xs text-muted-foreground">
                    Showing {displayRows.length} of {rows.length} transitions
                </span>
            )}

            <div className="mt-4 rounded-md bg-muted/50 p-3 text-sm text-muted-foreground">
                <strong className="text-foreground">{formatNumber(edges.length)}</strong> path transition
                {edges.length === 1 ? '' : 's'}
                {topUsers > 0 && (
                    <>
                        {' '}
                        · busiest carries <strong className="text-foreground">{formatNumber(topUsers)}</strong> users
                    </>
                )}
            </div>
        </div>
    )
}
