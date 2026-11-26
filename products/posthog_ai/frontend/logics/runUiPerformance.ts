export function observeRunUiPerformance(report: (properties: Record<string, number | boolean>) => void): () => void {
    const startedAt = performance.now()
    let count = 0
    let duration = 0
    let maxDuration = 0
    let blockingTime = 0
    let observer: PerformanceObserver | undefined
    const supported =
        typeof PerformanceObserver !== 'undefined' && PerformanceObserver.supportedEntryTypes?.includes('longtask')
    const collect = (entries: PerformanceEntry[]): void => {
        for (const entry of entries) {
            if (entry.startTime >= startedAt) {
                count++
                duration += entry.duration
                maxDuration = Math.max(maxDuration, entry.duration)
                blockingTime += Math.max(0, entry.duration - 50)
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
        if (observer) {
            collect(observer.takeRecords())
            observer.disconnect()
        }
        report({
            observed_duration_ms: Math.round(performance.now() - startedAt),
            long_task_supported: !!observer,
            long_task_count: count,
            long_task_duration_ms: Math.round(duration),
            max_long_task_duration_ms: Math.round(maxDuration),
            total_blocking_time_ms: Math.round(blockingTime),
        })
    }
}
