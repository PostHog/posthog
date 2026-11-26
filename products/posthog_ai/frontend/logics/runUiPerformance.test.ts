import { observeRunUiPerformance } from './runUiPerformance'

describe('run UI performance', () => {
    const originalObserver = Object.getOwnPropertyDescriptor(globalThis, 'PerformanceObserver')
    let callback: PerformanceObserverCallback
    let pending: PerformanceEntry[]
    const disconnect = jest.fn()
    class Observer {
        static supportedEntryTypes = ['longtask']
        observe = jest.fn()
        disconnect = disconnect
        takeRecords = (): PerformanceEntry[] => pending.splice(0)
        constructor(listener: PerformanceObserverCallback) {
            callback = listener
        }
    }

    beforeEach(() => {
        pending = []
        Object.defineProperty(globalThis, 'PerformanceObserver', { configurable: true, value: Observer })
        jest.spyOn(performance, 'now').mockReturnValue(100)
        disconnect.mockClear()
    })
    afterEach(() => {
        jest.restoreAllMocks()
        if (originalObserver) {
            Object.defineProperty(globalThis, 'PerformanceObserver', originalObserver)
        } else {
            delete (globalThis as { PerformanceObserver?: unknown }).PerformanceObserver
        }
    })

    it('counts only current observation tasks and drains pending records on stop', () => {
        const report = jest.fn()
        const stop = observeRunUiPerformance(report)
        callback(
            {
                getEntries: () => [
                    { startTime: 0, duration: 500 },
                    { startTime: 110, duration: 80 },
                ],
            } as PerformanceObserverEntryList,
            {} as PerformanceObserver
        )
        pending = [{ startTime: 200, duration: 120 } as PerformanceEntry]
        jest.mocked(performance.now).mockReturnValue(300)
        stop()
        expect(report).toHaveBeenCalledWith({
            observed_duration_ms: 200,
            long_task_supported: true,
            long_task_count: 2,
            long_task_duration_ms: 200,
            max_long_task_duration_ms: 120,
            total_blocking_time_ms: 100,
        })
        expect(disconnect).toHaveBeenCalled()
    })

    it('distinguishes an unsupported browser from a supported run without long tasks', () => {
        Object.defineProperty(globalThis, 'PerformanceObserver', { configurable: true, value: undefined })
        const report = jest.fn()
        observeRunUiPerformance(report)()
        expect(report).toHaveBeenCalledWith(expect.objectContaining({ long_task_supported: false, long_task_count: 0 }))
    })
})
