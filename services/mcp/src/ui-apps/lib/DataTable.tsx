import { ChevronLeft, ChevronRight } from 'lucide-react'
import { type ReactElement, type ReactNode, useCallback, useMemo, useState } from 'react'

// TODO(quill): delete this file once @posthog/quill ships a `DataTable` (or
// `Table` + `TableSort` + `TablePagination`) primitive. The prop shape below
// (`columns`, `data`, `pageSize`, `defaultSort`, `emptyMessage`) deliberately
// mirrors what we'd expect from a Quill primitive so migration is a single
// import swap.
//
// What's needed from Quill:
//   - A `Table` primitive with semantic `<table>/<thead>/<tbody>` markup —
//     accessibility relies on this and Quill currently ships no table
//     primitive (only `Item`/`ItemGroup`, which is row-per-item, not
//     row-of-columns). The data-density tradeoff is real: a 5-column metric
//     table doesn't render usefully as Item cards.
//   - Column-aware sorting wired to header click + ARIA
//     (`aria-sort=ascending|descending|none`). Today we hand-roll the toggle
//     between asc → desc → unsorted and the sort indicator glyphs.
//   - Client-side pagination with a token-styled control (we currently
//     compose `<Button variant="ghost" size="icon-xs">` + chevron icons
//     inline; a Quill `Pagination` primitive would absorb this).
//   - Empty state slot. We already route the "no data" branch through
//     `<Empty><EmptyHeader><EmptyDescription>` so the visual matches Quill's
//     primitive, but a real Quill `Table` could expose this directly via an
//     `emptyMessage` / `emptyState` prop.
//   - Built-in cell renderers (default text, number-localised,
//     boolean/null sentinel) — currently in `defaultFormat()` below.
//
// Until then this file leans on Quill's `Button`, `Empty*`, `cn()` and
// design tokens (`bg-muted/50`, `text-muted-foreground`, `border-t`,
// `--text-sm`) so the visual language already matches what a future Quill
// primitive would ship.
import { Button, cn, Empty, EmptyDescription, EmptyHeader } from '@posthog/quill'

export interface DataTableColumn<T> {
    key: string
    header: ReactNode
    render?: (row: T) => ReactNode
    align?: 'left' | 'center' | 'right'
    sortable?: boolean
}

export interface DataTableProps<T> {
    columns: DataTableColumn<T>[]
    data: T[]
    pageSize?: number
    defaultSort?: { key: string; direction: SortDirection }
    emptyMessage?: string
    className?: string
}

type SortDirection = 'asc' | 'desc'

interface SortState {
    key: string
    direction: SortDirection
}

function defaultFormat(value: unknown): string {
    if (value === null || value === undefined) {
        return '\u2014'
    }
    if (typeof value === 'number') {
        return value.toLocaleString()
    }
    if (typeof value === 'boolean') {
        return value ? 'true' : 'false'
    }
    if (typeof value === 'object') {
        return JSON.stringify(value)
    }
    return String(value)
}

function getValue(row: object, key: string): unknown {
    return (row as Record<string, unknown>)[key]
}

function compareValues(a: unknown, b: unknown): number {
    if (a === b) {
        return 0
    }
    if (a === null || a === undefined) {
        return 1
    }
    if (b === null || b === undefined) {
        return -1
    }
    if (typeof a === 'number' && typeof b === 'number') {
        return a - b
    }
    return String(a).localeCompare(String(b))
}

const alignClasses = {
    left: 'text-left',
    center: 'text-center',
    right: 'text-right',
} as const

function SortIcon({ direction, active }: { direction?: SortDirection | undefined; active: boolean }): ReactElement {
    return (
        <span
            className={cn(
                'inline-flex ml-1',
                active ? 'text-foreground' : 'text-muted-foreground opacity-0 group-hover/th:opacity-50'
            )}
        >
            {direction === 'asc' ? '\u2191' : direction === 'desc' ? '\u2193' : '\u2195'}
        </span>
    )
}

export function DataTable<T extends object>({
    columns,
    data,
    pageSize = 10,
    defaultSort,
    emptyMessage = 'No data',
    className,
}: DataTableProps<T>): ReactElement {
    const [sort, setSort] = useState<SortState | null>(defaultSort ?? null)
    const [page, setPage] = useState(0)

    const handleSort = useCallback((key: string) => {
        setSort((prev) => {
            if (prev?.key !== key) {
                return { key, direction: 'asc' }
            }
            if (prev.direction === 'asc') {
                return { key, direction: 'desc' }
            }
            return null
        })
        setPage(0)
    }, [])

    const sortedData = useMemo(() => {
        if (!sort) {
            return data
        }
        return [...data].sort((a, b) => {
            const cmp = compareValues(getValue(a, sort.key), getValue(b, sort.key))
            return sort.direction === 'desc' ? -cmp : cmp
        })
    }, [data, sort])

    const totalPages = pageSize > 0 ? Math.max(1, Math.ceil(sortedData.length / pageSize)) : 1
    const pagedData = pageSize > 0 ? sortedData.slice(page * pageSize, (page + 1) * pageSize) : sortedData
    const showPagination = pageSize > 0 && sortedData.length > pageSize

    if (data.length === 0) {
        return (
            <Empty className={cn('py-8', className)}>
                <EmptyHeader>
                    <EmptyDescription>{emptyMessage}</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    return (
        <div className={cn('overflow-hidden rounded-lg border', className)}>
            <div className="overflow-x-auto">
                <table className="w-full text-sm">
                    <thead>
                        <tr className="bg-muted/50">
                            {columns.map((col) => (
                                <th
                                    key={col.key}
                                    className={cn(
                                        'group/th px-3 py-2 font-medium text-muted-foreground',
                                        'max-w-[200px] truncate',
                                        alignClasses[col.align ?? 'left'],
                                        col.sortable && 'cursor-pointer select-none hover:text-foreground'
                                    )}
                                    title={typeof col.header === 'string' ? col.header : undefined}
                                    onClick={col.sortable ? () => handleSort(col.key) : undefined}
                                >
                                    {col.header}
                                    {col.sortable && (
                                        <SortIcon
                                            direction={sort?.key === col.key ? sort.direction : undefined}
                                            active={sort?.key === col.key}
                                        />
                                    )}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {pagedData.map((row, rowIndex) => (
                            <tr key={rowIndex} className={cn('border-t', rowIndex % 2 === 1 && 'bg-muted/25')}>
                                {columns.map((col) => {
                                    const content = col.render ? col.render(row) : defaultFormat(getValue(row, col.key))
                                    const title = typeof content === 'string' ? content : undefined

                                    return (
                                        <td
                                            key={col.key}
                                            className={cn(
                                                'px-3 py-2 text-foreground',
                                                'max-w-[200px] truncate',
                                                alignClasses[col.align ?? 'left']
                                            )}
                                            title={title}
                                        >
                                            {content}
                                        </td>
                                    )
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            {showPagination && (
                <div className="flex items-center justify-between border-t px-3 py-2 text-xs text-muted-foreground">
                    <span>
                        {page * pageSize + 1}&ndash;{Math.min((page + 1) * pageSize, sortedData.length)} of{' '}
                        {sortedData.length}
                    </span>
                    <div className="flex items-center gap-1">
                        <Button
                            variant="ghost"
                            size="icon-xs"
                            onClick={() => setPage((p) => Math.max(0, p - 1))}
                            disabled={page === 0}
                            aria-label="Previous page"
                        >
                            <ChevronLeft className="h-3.5 w-3.5" />
                        </Button>
                        <span className="px-1 tabular-nums">
                            {page + 1} / {totalPages}
                        </span>
                        <Button
                            variant="ghost"
                            size="icon-xs"
                            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                            disabled={page >= totalPages - 1}
                            aria-label="Next page"
                        >
                            <ChevronRight className="h-3.5 w-3.5" />
                        </Button>
                    </div>
                </div>
            )}
        </div>
    )
}
