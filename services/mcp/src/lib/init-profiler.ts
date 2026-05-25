// Per-init lifecycle profiler — records [label, elapsedMs, heapBytes?] at each
// mark and flushes one structured log line at the end of init(). Used to attribute
// the wallTime/cpuTime cost shown for `setName` in prod logs to the specific
// phase of init() that owns it (auth, tool registration, resource registration…).
//
// In dev with the V8 inspector attached, workerd exposes `performance.memory`,
// so `heapBytes` reflects `usedJSHeapSize` after each phase. In production the
// API isn't available and only timing data is emitted.
interface PerformanceWithMemory {
    memory?: { usedJSHeapSize?: number }
}

interface InitProfilerMark {
    label: string
    elapsedMs: number
    heapBytes?: number
}

export class InitProfiler {
    private readonly start: number
    private readonly marks: InitProfilerMark[] = []
    private flushed = false

    constructor() {
        this.start = performance.now()
    }

    mark(label: string): void {
        const memory = (performance as PerformanceWithMemory).memory
        const usedHeap = memory?.usedJSHeapSize
        const entry: InitProfilerMark = {
            label,
            elapsedMs: Math.round(performance.now() - this.start),
        }
        if (typeof usedHeap === 'number') {
            entry.heapBytes = usedHeap
        }
        this.marks.push(entry)
    }

    flush(extras?: Record<string, unknown>): void {
        if (this.flushed) {
            return
        }
        this.flushed = true
        console.info(
            JSON.stringify({
                event: 'mcp_init_timeline',
                totalMs: Math.round(performance.now() - this.start),
                marks: this.marks,
                ...extras,
            })
        )
    }
}
