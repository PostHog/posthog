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

    it.each([
        {
            name: 'task inside the window',
            startTime: 200,
            duration: 80,
            earlier: true,
            count: 2,
            overlap: 160,
            max: 80,
            blocking: 60,
        },
        {
            name: 'task ending after stop',
            startTime: 200,
            duration: 120,
            earlier: false,
            count: 1,
            overlap: 100,
            max: 100,
            blocking: 50,
        },
        {
            name: 'task starting before observation',
            startTime: 50,
            duration: 120,
            earlier: false,
            count: 1,
            overlap: 70,
            max: 70,
            blocking: 70,
        },
        {
            name: 'task spanning the window',
            startTime: 50,
            duration: 400,
            earlier: false,
            count: 1,
            overlap: 200,
            max: 200,
            blocking: 200,
        },
        {
            name: 'task ending at start',
            startTime: 0,
            duration: 100,
            earlier: false,
            count: 0,
            overlap: 0,
            max: 0,
            blocking: 0,
        },
        {
            name: 'task starting at stop',
            startTime: 300,
            duration: 100,
            earlier: false,
            count: 0,
            overlap: 0,
            max: 0,
            blocking: 0,
        },
    ])(
        'drains the final $name and clips durations to the window',
        ({ startTime, duration, earlier, count, overlap, max, blocking }) => {
            const reports: Record<string, number | boolean | string>[] = []
            const stop = observeRunUiPerformance((metrics) => reports.push(metrics))
            callback(
                {
                    getEntries: () => [
                        { startTime: 0, duration: 90 },
                        ...(earlier ? [{ startTime: 110, duration: 80 }] : []),
                    ],
                } as PerformanceObserverEntryList,
                {} as PerformanceObserver
            )
            jest.mocked(performance.now).mockReturnValue(300)
            stop()
            stop()
            expect(reports).toEqual([])
            pending = [
                { startTime, duration } as PerformanceEntry,
                { startTime: 310, duration: 500 } as PerformanceEntry,
            ]
            jest.mocked(performance.now).mockReturnValue(900)
            jest.runOnlyPendingTimers()
            expect(reports).toEqual([
                {
                    duration_policy: 'observation_window_overlap',
                    observed_duration_ms: 200,
                    long_task_supported: true,
                    long_task_count: count,
                    long_task_duration_ms: overlap,
                    max_long_task_duration_ms: max,
                    total_blocking_time_ms: blocking,
                },
            ])
            expect(observer.connected).toBe(false)
        }
    )

    it('distinguishes an unsupported browser from a supported run without long tasks', () => {
        Object.defineProperty(globalThis, 'PerformanceObserver', { configurable: true, value: undefined })
        const reports: Record<string, number | boolean | string>[] = []
        observeRunUiPerformance((metrics) => reports.push(metrics))()
        jest.runOnlyPendingTimers()
        expect(reports).toEqual([expect.objectContaining({ long_task_supported: false, long_task_count: 0 })])
    })
})
