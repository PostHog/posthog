import { ColumnDef } from '@tanstack/react-table'

import { Card, DataTable, Skeleton } from '@posthog/quill'

interface PlaceholderRow {
    id: string
    name: number
    status: number
}

const ROWS: PlaceholderRow[] = [
    { id: 'a', name: 46, status: 62 },
    { id: 'b', name: 34, status: 50 },
    { id: 'c', name: 58, status: 44 },
    { id: 'd', name: 40, status: 66 },
    { id: 'e', name: 52, status: 38 },
    { id: 'f', name: 30, status: 54 },
]

const bar = (className: string): (() => JSX.Element) =>
    function SkeletonBar(): JSX.Element {
        return <Skeleton className={className} />
    }

const COLUMNS: ColumnDef<PlaceholderRow>[] = [
    {
        id: 'name',
        header: 'Release',
        minSize: 256,
        enableSorting: false,
        meta: { expand: true },
        cell: ({ row }) => (
            <div className="flex flex-col gap-1.5 px-2 py-1">
                <Skeleton className="h-3" style={{ width: `${row.original.name}%` }} />
                <Skeleton className="h-2.5 opacity-60" style={{ width: `${row.original.status}%` }} />
            </div>
        ),
    },
    { id: 'stage', header: 'Stage', enableSorting: false, cell: bar('h-4 w-20 rounded-full') },
    { id: 'audience', header: 'Who gets it', enableSorting: false, cell: bar('h-2.5 w-24') },
    { id: 'owner', header: 'Owner', enableSorting: false, cell: bar('h-2.5 w-14') },
    { id: 'nextDate', header: 'Next date', enableSorting: false, cell: bar('h-2.5 w-16') },
    {
        id: 'nextStep',
        header: 'Next step',
        enableSorting: false,
        meta: { align: 'right' },
        cell: bar('ml-auto h-6 w-20'),
    },
]

export function ReleaseListSkeleton(): JSX.Element {
    return (
        <Card size="sm" flush className="pt-0" aria-busy aria-label="Loading releases">
            <DataTable columns={COLUMNS} data={ROWS} fullWidth size="sm" getRowId={(row) => row.id} />
        </Card>
    )
}
