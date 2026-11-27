import './SearchPerformanceTable.scss'

import { useMemo } from 'react'

import { DataTable, type DataTableProps, Empty, EmptyDescription, EmptyHeader, Skeleton } from '@posthog/quill'

import { QuillColumnHeaderTooltip } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/common/QuillColumnHeaderTooltip'

import { MarketingAnalyticsSearchRow } from '~/queries/schema/schema-general'

import { searchPerformanceRowKey } from './searchPerformance'

export interface SearchPerformanceColumn {
    key: string
    title: string
    tooltip?: string
    width: number
    numeric?: boolean
    sortValue?: (row: MarketingAnalyticsSearchRow) => number
    render: (row: MarketingAnalyticsSearchRow) => JSX.Element
}

type QuillColumns = DataTableProps<MarketingAnalyticsSearchRow, unknown>['columns']

const PAGE_SIZE = 10

export function QuillSearchPerformanceTable({
    columns,
    rows,
    loading,
    emptyState,
}: {
    columns: SearchPerformanceColumn[]
    rows: MarketingAnalyticsSearchRow[]
    loading: boolean
    emptyState: React.ReactNode
}): JSX.Element {
    const quillColumns = useMemo<QuillColumns>(
        () =>
            columns.map((column, index) => {
                const base = {
                    id: column.key,
                    header: () =>
                        column.tooltip ? (
                            <QuillColumnHeaderTooltip title={column.title} tooltip={column.tooltip} />
                        ) : (
                            column.title
                        ),
                    cell: ({ row }: { row: { original: MarketingAnalyticsSearchRow } }) => column.render(row.original),
                    meta: {
                        align: column.numeric ? ('right' as const) : undefined,
                        sticky: index === 0 ? ('left' as const) : undefined,
                    },
                }
                return column.sortValue
                    ? { ...base, accessorFn: column.sortValue, sortDescFirst: false }
                    : { ...base, enableSorting: false }
            }),
        [columns]
    )

    // The table stays mounted while loading so a reload keeps the sort.
    const empty = useMemo(
        () =>
            loading ? (
                <div className="flex flex-col gap-2" role="status" aria-label="Loading">
                    {Array.from({ length: PAGE_SIZE }, (_, index) => (
                        <Skeleton key={index} className="h-10" />
                    ))}
                </div>
            ) : typeof emptyState === 'string' ? (
                <Empty>
                    <EmptyHeader>
                        <EmptyDescription>{emptyState}</EmptyDescription>
                    </EmptyHeader>
                </Empty>
            ) : (
                emptyState
            ),
        [loading, emptyState]
    )
    const data = useMemo(() => (loading ? [] : rows), [loading, rows])

    return (
        <DataTable
            columns={quillColumns}
            data={data}
            getRowId={searchPerformanceRowKey}
            pageSize={data.length > PAGE_SIZE ? PAGE_SIZE : undefined}
            size="sm"
            fullWidth
            className="SearchPerformanceTable"
            empty={empty}
        />
    )
}
