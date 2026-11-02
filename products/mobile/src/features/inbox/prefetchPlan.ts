import type { InboxItem } from '@/model/types'

export const PREFETCH_LOOKAHEAD = 1
export const PREFETCH_CONCURRENCY = 1

export interface PrefetchRows {
    /** Report ids worth prefetching, in list order. */
    ids: string[]
    /** For each list row, the index in `ids` of the last prefetchable row at or before it, or -1. */
    idIndexByRow: number[]
}

// Done and dismissed rows are rarely opened first, so they do not use up the prefetch window.
export function prefetchRows(items: readonly Pick<InboxItem, 'reportId' | 'state'>[]): PrefetchRows {
    const ids: string[] = []
    const idIndexByRow: number[] = []
    for (const item of items) {
        if (item.state !== 'done' && item.state !== 'dismissed') {
            ids.push(item.reportId)
        }
        idIndexByRow.push(ids.length - 1)
    }
    return { ids, idIndexByRow }
}

export function prefetchWindow(
    ids: readonly string[],
    firstVisibleIndex: number | null,
    lastVisibleIndex: number | null
): string[] {
    if (firstVisibleIndex === null || lastVisibleIndex === null || lastVisibleIndex < firstVisibleIndex) return []
    return ids.slice(Math.max(0, firstVisibleIndex), lastVisibleIndex + PREFETCH_LOOKAHEAD + 1)
}

export interface PrefetchQueue {
    /** Replaces pending ids with this window, keeping any run already in flight. */
    enqueue(ids: readonly string[]): void
    /** Drops the pending ids. Runs in flight finish and still count toward the limit. */
    reset(): void
}

export function createPrefetchQueue(run: (id: string) => Promise<void>): PrefetchQueue {
    const running = new Set<string>()
    let pending: string[] = []

    const pump = (): void => {
        while (running.size < PREFETCH_CONCURRENCY && pending.length > 0) {
            const id = pending.shift() as string
            running.add(id)
            const settle = (): void => {
                running.delete(id)
                pump()
            }
            let result: Promise<void>
            try {
                result = run(id)
            } catch {
                result = Promise.resolve()
            }
            // A failed prefetch is not the user's problem: the report screen fetches again when it opens.
            result.then(settle, settle)
        }
    }

    return {
        enqueue(ids: readonly string[]): void {
            pending = [...new Set(ids)].filter((id) => !running.has(id))
            pump()
        },
        reset(): void {
            pending = []
        },
    }
}
