import { type ReactElement, type ReactNode, useMemo } from 'react'

// Thin adapter over Quill's `DataTable`: keeps the ergonomic
// `key`/`header`/`render`/`align`/`sortable` column shape (and default cell
// formatting) that list views read declaratively, and maps it onto Quill's
// `ColumnDef`. Quill handles pagination, per-column alignment, sorting, and the
// empty state; this layer only adapts the API and provides defaults.
import {
    cn,
    DataTable as QuillDataTable,
    type DataTableProps as QuillDataTableProps,
    Empty,
    EmptyDescription,
    EmptyHeader,
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

function defaultFormat(value: unknown): string {
    if (value === null || value === undefined) {
        return '—'
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

export function DataTable<T extends object>({
    columns,
    data,
    pageSize = 10,
    defaultSort,
    emptyMessage = 'No data',
    className,
}: DataTableProps<T>): ReactElement {
    // Quill's DataTable owns sorting from an empty initial state, so honour
    // `defaultSort` by pre-ordering the rows it receives.
    const sortedData = useMemo(() => {
        if (!defaultSort) {
            return data
        }
        return [...data].sort((a, b) => {
            const cmp = compareValues(getValue(a, defaultSort.key), getValue(b, defaultSort.key))
            return defaultSort.direction === 'desc' ? -cmp : cmp
        })
    }, [data, defaultSort])

    const quillColumns = useMemo<QuillDataTableProps<T, unknown>['columns']>(
        () =>
            columns.map((col): QuillDataTableProps<T, unknown>['columns'][number] => ({
                id: col.key,
                accessorFn: (row: T) => getValue(row, col.key),
                header: () => col.header,
                cell: (info: { getValue: () => unknown; row: { original: T } }) =>
                    col.render ? col.render(info.row.original) : defaultFormat(info.getValue()),
                enableSorting: col.sortable ?? false,
                meta: { align: col.align },
            })),
        [columns]
    )

    return (
        <QuillDataTable<T, unknown>
            columns={quillColumns}
            data={sortedData}
            className={cn('rounded-lg border', className)}
            {...(pageSize > 0 ? { pageSize } : {})}
            empty={
                <Empty className="py-8">
                    <EmptyHeader>
                        <EmptyDescription>{emptyMessage}</EmptyDescription>
                    </EmptyHeader>
                </Empty>
            }
        />
    )
}
