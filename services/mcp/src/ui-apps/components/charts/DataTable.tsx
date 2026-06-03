import type { ReactElement } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'

import { formatNumber } from '../utils'

// TODO(quill): same blocker as `lib/DataTable.tsx` — Quill ships no `Table`
// primitive. This is the chart-results variant: a fixed-height query-result
// table with a chart-style empty illustration. It would also collapse into a
// future Quill `Table` once the primitive lands; until then it stays
// distinct from `lib/DataTable.tsx` because it has different defaults
// (smaller cell width, max-row truncation, illustrated empty state).

const MAX_ROWS = 20
const MAX_CELL_WIDTH = 200

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

export interface DataTableProps {
    columns: string[]
    rows: unknown[][]
    maxRows?: number
}

export function DataTable({ columns, rows, maxRows = MAX_ROWS }: DataTableProps): ReactElement {
    const displayRows = rows.slice(0, maxRows)
    const hasMore = displayRows.length < rows.length

    if (columns.length === 0 && rows.length === 0) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyMedia>{emptyStateIllustration('table')}</EmptyMedia>
                    <EmptyDescription>No rows to display</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    if (rows.length === 0) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyMedia>{emptyStateIllustration('table')}</EmptyMedia>
                    <EmptyDescription>Query returned no rows</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    return (
        <div style={{ overflowX: 'auto' }}>
            <table
                style={{
                    width: '100%',
                    borderCollapse: 'collapse',
                    fontSize: '0.8125rem',
                }}
            >
                <thead>
                    <tr>
                        {columns.map((col, i) => (
                            <th
                                key={i}
                                style={{
                                    padding: '0.5rem 0.75rem',
                                    textAlign: 'left',
                                    fontWeight: 600,
                                    color: 'var(--color-text-primary, #101828)',
                                    borderBottom: '2px solid var(--color-border-primary, #e5e7eb)',
                                    backgroundColor: 'var(--color-background-secondary, #f9fafb)',
                                    maxWidth: `${MAX_CELL_WIDTH}px`,
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                    whiteSpace: 'nowrap',
                                }}
                                title={col}
                            >
                                {col}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {displayRows.map((row, rowIndex) => (
                        <tr
                            key={rowIndex}
                            style={{
                                backgroundColor:
                                    rowIndex % 2 === 0
                                        ? 'var(--color-background-primary, #fff)'
                                        : 'var(--color-background-secondary, #f9fafb)',
                            }}
                        >
                            {columns.map((_, colIndex) => {
                                const value = row[colIndex]
                                const formatted = formatCellValue(value)
                                return (
                                    <td
                                        key={colIndex}
                                        style={{
                                            padding: '0.5rem 0.75rem',
                                            color: 'var(--color-text-primary, #101828)',
                                            borderBottom: '1px solid var(--color-border-primary, #e5e7eb)',
                                            maxWidth: `${MAX_CELL_WIDTH}px`,
                                            overflow: 'hidden',
                                            textOverflow: 'ellipsis',
                                            whiteSpace: 'nowrap',
                                        }}
                                        title={formatted}
                                    >
                                        {formatted}
                                    </td>
                                )
                            })}
                        </tr>
                    ))}
                </tbody>
            </table>

            {hasMore && (
                <div
                    style={{
                        padding: '0.75rem',
                        textAlign: 'center',
                        color: 'var(--color-text-secondary, #6b7280)',
                        fontSize: '0.8125rem',
                        borderTop: '1px solid var(--color-border-primary, #e5e7eb)',
                    }}
                >
                    Showing {displayRows.length} of {rows.length}+ rows
                </div>
            )}
        </div>
    )
}
