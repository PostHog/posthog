import { useValues } from 'kea'

import { Dot, Skeleton, Text } from '@posthog/quill'

import type { ReleaseAllRow } from './releaseAllLogic'
import { releaseLogic } from './releaseLogic'
import { ReleaseStageDot } from './ReleaseStageDot'

export function ReleaseAllStatus({ row }: { row: ReleaseAllRow }): JSX.Element {
    const { loadFailed } = useValues(releaseLogic)
    if (row.type === 'release' && !row.stage && loadFailed) {
        return (
            <Text size="xs" variant="muted">
                –
            </Text>
        )
    }
    if (row.type === 'release' && !row.stage) {
        return (
            <span className="flex items-center gap-1.5" aria-label="Loading status">
                <Skeleton className="size-2 rounded-full" />
                <Skeleton className="h-2.5 w-14" />
            </span>
        )
    }
    return (
        <span className="flex items-center gap-1.5 whitespace-nowrap">
            <span className="flex size-3 shrink-0 items-center justify-center">
                {row.stage ? <ReleaseStageDot stage={row.stage} /> : <Dot variant={row.tone} className="p-0" />}
            </span>
            <Text size="xs">{row.status}</Text>
        </span>
    )
}
