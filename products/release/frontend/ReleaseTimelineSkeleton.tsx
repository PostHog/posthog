import { ColumnDef } from '@tanstack/react-table'
import { useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { DataTable, Skeleton } from '@posthog/quill'

import { ReleaseTimelineAxis } from './ReleaseTimelineAxis'
import { ReleaseTrackGrid } from './ReleaseTrackGrid'
import { CALENDAR_SCALE } from './releaseTracks'
import { CALENDAR_DAYS_BEFORE } from './releaseUtils'
import { useScrollToToday } from './useScrollToToday'

interface PlaceholderRow {
    id: string
    name: number
    status: number
    from: number
}

const ROWS: PlaceholderRow[] = [
    { id: 'a', name: 52, status: 70, from: 0 },
    { id: 'b', name: 40, status: 55, from: 0.35 },
    { id: 'c', name: 64, status: 48, from: 0.15 },
    { id: 'd', name: 46, status: 62, from: 0.45 },
    { id: 'e', name: 58, status: 44, from: 0.05 },
    { id: 'f', name: 36, status: 58, from: 0.25 },
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
    const start = row.original.from * today
    return (
        <div className="relative" style={{ width: scale.days * scale.day, height: ROW_HEIGHT }}>
            <ReleaseTrackGrid scale={scale} />
            <Skeleton className="absolute h-5 rounded-full" style={{ left: start, width: today - start, top: 26 }} />
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
    const [container, setContainer] = useState<HTMLDivElement | null>(null)
    useScrollToToday(container, CALENDAR_SCALE(), true)
    return (
        <div ref={setContainer} aria-busy aria-label="Loading releases">
            <DataTable columns={COLUMNS} data={ROWS} size="sm" getRowId={(row) => row.id} />
        </div>
    )
}
