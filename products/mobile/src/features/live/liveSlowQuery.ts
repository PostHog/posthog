import { addSessionEndTask } from '@/auth/authStore'
import { isRecord } from '@/lib/records'

interface SlowRead {
    attemptedAt: number
    fetchedAt: number | null
    signal?: AbortSignal
    answer: Promise<unknown>
}
// Each arbitrary host/path combination has a separate hourly result. Bound retained combinations per session.
const MAX_CACHED_READS = 32
const reads = new Map<string, SlowRead>()
addSessionEndTask(() => reads.clear())

export function clearSlowLiveQuery(scope: string): void {
    for (const key of reads.keys()) {
        if (key.startsWith(`${scope}|`)) reads.delete(key)
    }
}

export function readSlowLiveQuery(
    key: string,
    now: number,
    read: () => Promise<unknown>,
    signal?: AbortSignal
): Promise<unknown> {
    const cached = reads.get(key)
    if (
        cached &&
        !(cached.fetchedAt === null && cached.signal?.aborted) &&
        (now - cached.attemptedAt < 60_000 || (cached.fetchedAt !== null && now - cached.fetchedAt < 60 * 60_000))
    ) {
        reads.delete(key)
        reads.set(key, cached)
        return cached.answer
    }
    const entry: SlowRead = {
        signal,
        attemptedAt: now,
        fetchedAt: null,
        answer: Promise.resolve(null),
    }
    entry.answer = read().then((value) => {
        if (!isRecord(value) || !Array.isArray(value.results))
            throw new Error('The mobile metrics query did not finish.')
        entry.fetchedAt = now
        return { ...value, liveFetchedAt: now }
    })
    reads.delete(key)
    reads.set(key, entry)
    if (reads.size > MAX_CACHED_READS) {
        const oldest = reads.keys().next()
        if (!oldest.done) reads.delete(oldest.value)
    }
    return entry.answer
}
