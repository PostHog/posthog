import { ApiError } from 'lib/api-error'

/**
 * Report ids the report endpoint answered 404 for.
 *
 * Deletion is terminal, and a deleted report is unreachable by id, but the scout run rows keep
 * naming it. Without this the roster asks for the same dead ids on every load and every 60 second
 * poll, for the whole life of the page. Module-level so the two report readers (the fleet findings
 * feed and the per-scout detail view) share one answer across mounts.
 */
const unreachableReportIds = new Set<string>()

export function isReportUnreachable(id: string): boolean {
    return unreachableReportIds.has(id)
}

/**
 * Remember a failure, and report whether it was terminal. Only a 404 is remembered. Every other
 * failure can be transient, so the id stays retryable.
 */
export function rememberUnreachableReport(id: string, reason: unknown): boolean {
    if (!(reason instanceof ApiError) || reason.status !== 404) {
        return false
    }
    unreachableReportIds.add(id)
    return true
}

/** Test-only: the set outlives a logic mount by design. */
export function forgetUnreachableReports(): void {
    unreachableReportIds.clear()
}
