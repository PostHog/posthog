import { observeRunUiPerformance } from './runUiPerformance'

describe('run UI performance', () => {
    const originalObserver = Object.getOwnPropertyDescriptor(globalThis, 'PerformanceObserver')
    let callback: PerformanceObserverCallback
    let pending: PerformanceEntry[]
    let observer: Observer
    class Observer {
        static supportedEntryTypes = ['longtask']
        connected = false
        observe = (): void => {
            this.connected = true
        }
        disconnect = (): void => {
            this.connected = false
        }
        takeRecords = (): PerformanceEntry[] => pending.splice(0)
        constructor(listener: PerformanceObserverCallback) {
            callback = listener
            observer = this
        }
    }

    beforeEach(() => {
        jest.useFakeTimers()
        pending = []
        Object.defineProperty(globalThis, 'PerformanceObserver', { configurable: true, value: Observer })
        jest.spyOn(performance, 'now').mockReturnValue(100)
    })
    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
        if (originalObserver) {
            Object.defineProperty(globalThis, 'PerformanceObserver', originalObserver)
        } else {
            delete (globalThis as { PerformanceObserver?: unknown }).PerformanceObserver
        }
    })

    it('drains the completed final task without counting work after the observation ends', () => {
        const reports: Record<string, number | boolean>[] = []
        const stop = observeRunUiPerformance((metrics) => reports.push(metrics))
        callback(
            {
                getEntries: () => [
                    { startTime: 0, duration: 500 },
                    { startTime: 110, duration: 80 },
                ],
            } as PerformanceObserverEntryList,
            {} as PerformanceObserver
        )
        jest.mocked(performance.now).mockReturnValue(300)
        stop()
        stop()
        expect(reports).toEqual([])
        pending = [
            { startTime: 200, duration: 120 } as PerformanceEntry,
            { startTime: 310, duration: 500 } as PerformanceEntry,
        ]
        jest.mocked(performance.now).mockReturnValue(900)
        jest.runOnlyPendingTimers()
        expect(reports).toEqual([
            {
                observed_duration_ms: 200,
                long_task_supported: true,
                long_task_count: 2,
                long_task_duration_ms: 200,
                max_long_task_duration_ms: 120,
                total_blocking_time_ms: 100,
            },
        ])
        expect(observer.connected).toBe(false)
    })

    it('distinguishes an unsupported browser from a supported run without long tasks', () => {
        Object.defineProperty(globalThis, 'PerformanceObserver', { configurable: true, value: undefined })
        const reports: Record<string, number | boolean>[] = []
        observeRunUiPerformance((metrics) => reports.push(metrics))()
        jest.runOnlyPendingTimers()
        expect(reports).toEqual([expect.objectContaining({ long_task_supported: false, long_task_count: 0 })])
    })
})
