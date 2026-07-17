/** Cache key for a run's jobs, keyed by attempt so a re-run's attempts don't overwrite each other. */
export function jobCacheKey(runId: number, runAttempt: number | null): string {
    return `${runId}:${runAttempt ?? 'latest'}`
}
