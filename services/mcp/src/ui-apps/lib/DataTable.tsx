import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, ChevronsUpDown } from 'lucide-react'
import { type ReactElement, type ReactNode, useCallback, useMemo, useState } from 'react'

// Composes Quill's `Table` primitive (semantic markup, sticky-capable, scroll
// affordances) and layers on the pieces Quill's `DataTable` component doesn't
// cover: client-side pagination, per-column alignment, and default cell
// formatting (number-localise, boolean/null sentinel). The simpler
// `DataTableColumn` shape — `key`/`header`/`render`/`align`/`sortable` — is kept
// over TanStack's `ColumnDef` so list views read declaratively. Drop this in
// favour of Quill's `DataTable` directly once it gains pagination + alignment.
import {
    Button,
    cn,
    Empty,
    EmptyDescription,
    EmptyHeader,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@posthog/quill'

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

function SortIndicator({ direction }: { direction?: SortDirection | undefined }): ReactElement {
    if (direction === 'asc') {
        return <ArrowUp className="size-3" />
    }
    if (direction === 'desc') {
        return <ArrowDown className="size-3" />
    }
    return <ChevronsUpDown className="size-3 opacity-50" />
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
    // Clamp during render so an out-of-range `page` (e.g. parent passed a shorter `data`)
    // can't render an empty body with no empty-state fallback.
    const safePage = Math.min(page, totalPages - 1)
    const pagedData = pageSize > 0 ? sortedData.slice(safePage * pageSize, (safePage + 1) * pageSize) : sortedData
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
            <Table>
                <TableHeader>
                    <TableRow>
                        {columns.map((col) => {
                            const active = sort?.key === col.key
                            return (
                                <TableHead
                                    key={col.key}
                                    aria-sort={
                                        col.sortable
                                            ? active
                                                ? sort?.direction === 'asc'
                                                    ? 'ascending'
                                                    : 'descending'
                                                : 'none'
                                            : undefined
                                    }
                                    className={cn('max-w-[200px] truncate', alignClasses[col.align ?? 'left'])}
                                    title={typeof col.header === 'string' ? col.header : undefined}
                                >
                                    {col.sortable ? (
                                        <Button
                                            size="sm"
                                            aria-selected={active ? true : undefined}
                                            className={cn('gap-1.5', active && 'text-foreground')}
                                            onClick={() => handleSort(col.key)}
                                        >
                                            {col.header}
                                            <SortIndicator direction={active ? sort?.direction : undefined} />
                                        </Button>
                                    ) : (
                                        col.header
                                    )}
                                </TableHead>
                            )
                        })}
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {pagedData.map((row, rowIndex) => (
                        <TableRow key={rowIndex}>
                            {columns.map((col) => {
                                const content = col.render ? col.render(row) : defaultFormat(getValue(row, col.key))
                                const title = typeof content === 'string' ? content : undefined

                                return (
                                    <TableCell
                                        key={col.key}
                                        className={cn('max-w-[200px] truncate', alignClasses[col.align ?? 'left'])}
                                        title={title}
                                    >
                                        {content}
                                    </TableCell>
                                )
                            })}
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
            {showPagination && (
                <div className="flex items-center justify-between border-t px-3 py-2 text-xs text-muted-foreground">
                    <span>
                        {safePage * pageSize + 1}&ndash;{Math.min((safePage + 1) * pageSize, sortedData.length)} of{' '}
                        {sortedData.length}
                    </span>
                    <div className="flex items-center gap-1">
                        <Button
                            variant="ghost"
                            size="icon-xs"
                            onClick={() => setPage(Math.max(0, safePage - 1))}
                            disabled={safePage === 0}
                            aria-label="Previous page"
                        >
                            <ChevronLeft className="h-3.5 w-3.5" />
                        </Button>
                        <span className="px-1 tabular-nums">
                            {safePage + 1} / {totalPages}
                        </span>
                        <Button
                            variant="ghost"
                            size="icon-xs"
                            onClick={() => setPage(Math.min(totalPages - 1, safePage + 1))}
                            disabled={safePage >= totalPages - 1}
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
