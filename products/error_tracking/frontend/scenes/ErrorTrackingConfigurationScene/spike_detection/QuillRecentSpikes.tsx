import { useActions, useValues } from 'kea'

import { Button, DataTable, DataTableProps, Skeleton, cn } from '@posthog/quill'

import { ErrorTrackingSpikeEvent } from 'lib/components/Errors/types'
import { QuillTablePagination } from 'lib/components/QuillTablePagination/QuillTablePagination'
import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SpikeEventOrder, recentSpikesLogic } from './recentSpikesLogic'

const COLUMNS: DataTableProps<ErrorTrackingSpikeEvent, unknown>['columns'] = [
    {
        id: 'issue',
        header: 'Issue',
        enableSorting: false,
        cell: ({ row }) => (
            <Button
                variant="link-foreground"
                size="sm"
                nativeButton={false}
                render={<LinkPrimitive to={urls.errorTrackingIssue(row.original.issue.id)} />}
            >
                {row.original.issue.name || 'Unknown issue'}
            </Button>
        ),
    },
    {
        accessorKey: 'detected_at',
        header: 'Detected at',
        cell: ({ row }) => <TZLabel time={row.original.detected_at} />,
    },
    {
        accessorKey: 'computed_baseline',
        header: 'Baseline',
        cell: ({ row }) => <span translate="no">{Math.round(row.original.computed_baseline)}</span>,
    },
    {
        accessorKey: 'current_bucket_value',
        header: 'Multiplier',
        cell: ({ row }) => {
            const record = row.original
            const multiplier =
                record.computed_baseline > 0
                    ? Math.round(record.current_bucket_value / record.computed_baseline)
                    : record.current_bucket_value

            return <span translate="no">{multiplier}x</span>
        },
    },
]

export function QuillRecentSpikes(): JSX.Element {
    const { recentSpikes, spikesResponseLoading, pagination, order } = useValues(recentSpikesLogic)
    const { setOrder, setPage } = useActions(recentSpikesLogic)

    const descending = order.startsWith('-')
    const columnKey = descending ? order.slice(1) : order
    const pageCount = Math.ceil(pagination.entryCount / pagination.pageSize)

    if (spikesResponseLoading && recentSpikes.length === 0) {
        return (
            <div className="flex flex-col gap-2">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div
                className={cn('transition-opacity', spikesResponseLoading && 'opacity-60')}
                aria-busy={spikesResponseLoading}
            >
                <DataTable
                    columns={COLUMNS}
                    data={recentSpikes}
                    fullWidth
                    sorting={[{ id: columnKey, desc: descending }]}
                    onSortingChange={([sort]) => {
                        // The table never shows an unsorted state, so a click that would clear the sort flips it.
                        if (!sort) {
                            setOrder((descending ? columnKey : `-${columnKey}`) as SpikeEventOrder)
                            return
                        }
                        setOrder(`${sort.desc ? '-' : ''}${sort.id}` as SpikeEventOrder)
                    }}
                    empty="No spike events detected yet."
                />
            </div>
            {pageCount > 1 && (
                <QuillTablePagination
                    currentPage={pagination.currentPage}
                    pageCount={pageCount}
                    pageSize={pagination.pageSize}
                    total={pagination.entryCount}
                    onPageChange={setPage}
                />
            )}
        </div>
    )
}
