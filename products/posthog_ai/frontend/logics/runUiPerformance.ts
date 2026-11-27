export function observeRunUiPerformance(
    report: (properties: Record<string, number | boolean | string>) => void
): () => void {
    const startedAt = performance.now()
    let stoppedAt: number | undefined
    let count = 0
    let duration = 0
    let maxDuration = 0
    let blockingTime = 0
    let observer: PerformanceObserver | undefined
    const supported =
        typeof PerformanceObserver !== 'undefined' && PerformanceObserver.supportedEntryTypes?.includes('longtask')
    const collect = (entries: PerformanceEntry[]): void => {
        for (const entry of entries) {
            const overlapEnd = Math.min(entry.startTime + entry.duration, stoppedAt ?? Infinity)
            const overlapDuration = overlapEnd - Math.max(entry.startTime, startedAt)
            if (overlapDuration > 0) {
                count++
                duration += overlapDuration
                maxDuration = Math.max(maxDuration, overlapDuration)
                blockingTime += Math.max(0, overlapEnd - Math.max(entry.startTime + 50, startedAt))
            }
        }
    }
    if (supported) {
        try {
            observer = new PerformanceObserver((list) => collect(list.getEntries()))
            observer.observe({ type: 'longtask' })
        } catch {
            observer?.disconnect()
            observer = undefined
        }
    }
    return () => {
        if (stoppedAt !== undefined) {
            return
        }
        stoppedAt = performance.now()
        const observedDuration = Math.round(stoppedAt - startedAt)
        setTimeout(() => {
            if (observer) {
                collect(observer.takeRecords())
                observer.disconnect()
            }
            report({
                duration_policy: 'observation_window_overlap',
                observed_duration_ms: observedDuration,
                long_task_supported: !!observer,
                long_task_count: count,
                long_task_duration_ms: Math.round(duration),
                max_long_task_duration_ms: Math.round(maxDuration),
                total_blocking_time_ms: Math.round(blockingTime),
            })
        }, 0)
    }
}
