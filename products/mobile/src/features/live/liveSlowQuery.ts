import { addSessionEndTask } from '@/auth/authStore'
import { isRecord } from '@/lib/records'

interface SlowRead {
    attemptedAt: number
    fetchedAt: number | null
    answer: Promise<unknown>
}
const reads = new Map<string, SlowRead>()
addSessionEndTask(() => reads.clear())

export function readSlowLiveQuery(key: string, now: number, read: () => Promise<unknown>): Promise<unknown> {
    const cached = reads.get(key)
    if (
        cached &&
        (now - cached.attemptedAt < 60_000 || (cached.fetchedAt !== null && now - cached.fetchedAt < 60 * 60_000))
    )
        return cached.answer
    const entry: SlowRead = {
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
    reads.set(key, entry)
    return entry.answer
}
