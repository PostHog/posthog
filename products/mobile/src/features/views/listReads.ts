import { BudgetExceededError, type BudgetFamily } from '@/api/budget'
import { ApiError } from '@/api/client'
import { retryUnlessMissing } from '@/api/reports'

import { viewsQueue } from './refreshQueue'
import { reportScopeError } from './useViewsAccess'

// The pin list, Recent, Browse and search are TanStack queries, not queue jobs, because they page and search. They
// still share the queue's family pause, so a 429 or 503 on any Views read holds every read of that family for its
// `Retry-After`.

/**
 * TanStack `retry` for these reads: once after a network error, never after a 429 or 503 (the family pause waits for
 * `Retry-After` instead), an empty budget bucket, or a missing view or scope.
 */
export function retryListRead(failureCount: number, error: unknown): boolean {
    if (error instanceof ApiError && (error.status === 429 || error.status === 503)) {
        return false
    }
    return !(error instanceof BudgetExceededError) && retryUnlessMissing(failureCount, error)
}

/** Runs one list read after the family's pause ends. A 429 or 503 pauses the family; a missing scope shows sign-in. */
export async function listRead<T>(
    family: BudgetFamily,
    signal: AbortSignal | undefined,
    read: () => Promise<T>
): Promise<T> {
    await viewsQueue.whenFamilyReady(family, signal)
    try {
        return await read()
    } catch (error) {
        viewsQueue.notePause(family, error)
        reportScopeError(error)
        throw error
    }
}
