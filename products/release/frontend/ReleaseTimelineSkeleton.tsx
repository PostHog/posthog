import { ColumnDef } from '@tanstack/react-table'

import { IconChevronRight } from '@posthog/icons'
import { DataTable, Skeleton } from '@posthog/quill'

import { ReleaseTimelineAxis } from './ReleaseTimelineAxis'
import { ReleaseTrackGrid } from './ReleaseTrackGrid'
import { CALENDAR_SCALE } from './releaseTracks'
import { CALENDAR_DAYS_BEFORE } from './releaseUtils'

interface PlaceholderRow {
    id: string
    name: number
    status: number
    from: number
    to: number
    rise: number
}

const ROWS: PlaceholderRow[] = [
    { id: 'a', name: 52, status: 70, from: 0, to: 0.55, rise: 12 },
    { id: 'b', name: 40, status: 55, from: 0.35, to: 0.7, rise: 6 },
    { id: 'c', name: 64, status: 48, from: 0.15, to: 0.4, rise: 16 },
    { id: 'd', name: 46, status: 62, from: 0.45, to: 0.8, rise: 4 },
    { id: 'e', name: 58, status: 44, from: 0.05, to: 0.3, rise: 10 },
    { id: 'f', name: 36, status: 58, from: 0.25, to: 0.6, rise: 14 },
]

const ROW_HEIGHT = 60

function NameCell({ row }: { row: { original: PlaceholderRow } }): JSX.Element {
    return (
        <div className="flex items-center gap-2" style={{ width: 288, height: ROW_HEIGHT }}>
            <IconChevronRight className="size-3.5 shrink-0 text-muted-foreground opacity-40" />
            <Skeleton className="size-2 shrink-0 rounded-full" />
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                <Skeleton className="h-3" style={{ width: `${row.original.name}%` }} />
                <Skeleton className="h-2.5 opacity-60" style={{ width: `${row.original.status}%` }} />
            </div>
        </div>
    )
}

function TimelineCell({ row }: { row: { original: PlaceholderRow } }): JSX.Element {
    const scale = CALENDAR_SCALE()
    const today = (CALENDAR_DAYS_BEFORE + 0.5) * scale.day
    const { from, to, rise } = row.original
    const start = from * today
    const step = to * today
    return (
        <div className="relative" style={{ width: scale.days * scale.day, height: ROW_HEIGHT }}>
            <ReleaseTrackGrid scale={scale} />
            <Skeleton className="absolute h-0.5" style={{ left: start, width: step - start, top: 46 }} />
            <Skeleton className="absolute w-0.5" style={{ left: step, height: rise, top: 46 - rise }} />
            <Skeleton className="absolute h-0.5" style={{ left: step, width: today - step, top: 46 - rise }} />
            <Skeleton className="absolute h-2.5 w-8" style={{ left: step + 4, top: 32 - rise }} />
        </div>
    )
}

const COLUMNS: ColumnDef<PlaceholderRow>[] = [
    { id: 'release', header: 'Release', size: 300, enableSorting: false, meta: { sticky: 'left' }, cell: NameCell },
    {
        id: 'timeline',
        header: () => <ReleaseTimelineAxis scale={CALENDAR_SCALE()} />,
        enableSorting: false,
        cell: TimelineCell,
    },
]

export function ReleaseTimelineSkeleton(): JSX.Element {
    return (
        <div aria-busy aria-label="Loading releases">
            <DataTable columns={COLUMNS} data={ROWS} size="sm" getRowId={(row) => row.id} />
        </div>
    )
}
