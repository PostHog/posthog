/** Cache key for a run's jobs — keyed by attempt so a re-run's attempts don't overwrite each other.
 *  Shared by the logics that lazily load jobs and the RunsTable that reads the cache. */
export function jobCacheKey(runId: number, runAttempt: number | null): string {
    return `${runId}:${runAttempt ?? 'latest'}`
}
