import { INBOX_PAGE_SIZE } from '@/api/reports'
import type { InboxItem } from '@/model/types'

/** The first two pages of the list: the reports a session most likely opens. */
export const INITIAL_PREFETCH_COUNT = 2 * INBOX_PAGE_SIZE
export const PREFETCH_LOOKAHEAD = 5
/** Reports in flight at once. Each report is 3 to 4 requests. */
export const PREFETCH_CONCURRENCY = 2

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

/** The ids to prefetch, given the last visible index in `ids`, or `null` before the list reports what is visible. */
export function prefetchWindow(ids: readonly string[], lastVisibleIndex: number | null): string[] {
    const last =
        lastVisibleIndex === null
            ? INITIAL_PREFETCH_COUNT - 1
            : Math.max(INITIAL_PREFETCH_COUNT - 1, lastVisibleIndex + PREFETCH_LOOKAHEAD)
    return ids.slice(0, last + 1)
}

export interface PrefetchQueue {
    /** Queues the ids that are not already pending or running. An id runs again once its last run settles. */
    enqueue(ids: readonly string[]): void
    /** Drops the pending ids. Runs in flight finish and still count toward the limit. */
    reset(): void
}

// Dedupes only queued and running ids: the prefetch stale time makes a repeat run of a fresh report a no-op, and a
// report the cache dropped while idle is fetched again when it comes back into view.
export function createPrefetchQueue(run: (id: string) => Promise<void>): PrefetchQueue {
    let active = new Set<string>()
    let pending: string[] = []
    let inFlight = 0

    const pump = (): void => {
        while (inFlight < PREFETCH_CONCURRENCY && pending.length > 0) {
            const id = pending.shift() as string
            const owner = active
            inFlight += 1
            const settle = (): void => {
                inFlight -= 1
                owner.delete(id)
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
            for (const id of ids) {
                if (!active.has(id)) {
                    active.add(id)
                    pending.push(id)
                }
            }
            pump()
        },
        reset(): void {
            // A new set, so a run from before the reset does not clear an id queued after it.
            active = new Set()
            pending = []
        },
    }
}
