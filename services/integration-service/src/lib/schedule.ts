/**
 * Run a periodic task with a fresh delay drawn from [intervalMs/2, intervalMs] each tick,
 * so replicas do not sync up. The period never exceeds intervalMs: the reload cadence is
 * the signing-key revocation path, so it must not stretch past the documented interval.
 *
 * Timers are unref'd so a pending one never holds the process open during shutdown.
 * Returns a cancel function.
 */
export function scheduleJittered(intervalMs: number, task: () => Promise<void>): () => void {
    let timer: NodeJS.Timeout | undefined
    let cancelled = false
    const arm = (): void => {
        if (cancelled) {
            return
        }
        timer = setTimeout(
            () => {
                void task().finally(arm)
            },
            intervalMs / 2 + Math.random() * (intervalMs / 2)
        )
        timer.unref()
    }
    arm()
    return () => {
        cancelled = true
        clearTimeout(timer)
    }
}
