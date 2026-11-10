import { LiveController, type LiveControllerEvent, type LiveReadResult, liveStatus } from './liveController'

interface Read {
    signal: AbortSignal
    resolve: (result: LiveReadResult<string>) => void
    reject: (error: Error) => void
}

describe('LiveController', () => {
    let reads: Read[]
    let events: LiveControllerEvent[]
    let controller: LiveController<string>

    function lastRead(): Read {
        const read = reads.at(-1)
        if (!read) {
            throw new Error('no read started')
        }
        return read
    }

    async function answer(result: LiveReadResult<string> | Error): Promise<void> {
        const read = lastRead()
        if (result instanceof Error) {
            read.reject(result)
        } else {
            read.resolve(result)
        }
        await jest.advanceTimersByTimeAsync(0)
    }

    beforeEach(() => {
        jest.useFakeTimers()
        reads = []
        events = []
        controller = new LiveController<string>({
            read: (signal) =>
                new Promise<LiveReadResult<string>>((resolve, reject) => reads.push({ signal, resolve, reject })),
            intervalMs: 30_000,
            graceMs: 2000,
            maxBackoffMs: 300_000,
            slowdown: { afterMs: 10 * 60_000, intervalMs: 60_000 },
            onChange: () => undefined,
            onEvent: (event) => events.push(event),
        })
    })

    afterEach(() => {
        controller.dispose()
        jest.useRealTimers()
    })

    test('reads on focus, polls from the end of each read, and stops every tick while paused', async () => {
        controller.setVisible(true)
        expect(reads).toHaveLength(1)
        await answer({ data: 'a', complete: true })

        await jest.advanceTimersByTimeAsync(30_000)
        expect(reads).toHaveLength(2)

        controller.pause()
        expect(lastRead().signal.aborted).toBe(true)
        await jest.advanceTimersByTimeAsync(10 * 60_000)
        expect(reads).toHaveLength(2)
        expect(liveStatus(controller.current)).toBe('paused')

        void controller.resume()
        expect(reads).toHaveLength(3)
        await answer({ data: 'b', complete: true })
        expect(controller.current.data).toBe('b')
        await jest.advanceTimersByTimeAsync(30_000)
        expect(reads).toHaveLength(4)

        controller.setVisible(false)
        expect(lastRead().signal.aborted).toBe(true)
        await jest.advanceTimersByTimeAsync(10 * 60_000)
        expect(reads).toHaveLength(4)
    })

    test.each(['timer fired', 'JavaScript suspended'])(
        'the foreground reads at once after the background grace (%s)',
        async (background) => {
            controller.setVisible(true)
            await answer({ data: 'a', complete: true })

            controller.setForeground(false)
            await jest.advanceTimersByTimeAsync(1000)
            controller.setForeground(true)
            expect(reads).toHaveLength(1)
            await jest.advanceTimersByTimeAsync(29_000)
            expect(reads).toHaveLength(2)
            await answer({ data: 'b', complete: true })

            controller.setForeground(false)
            if (background === 'timer fired') {
                await jest.advanceTimersByTimeAsync(2000)
                expect(events).toEqual(['background_stopped'])
                await jest.advanceTimersByTimeAsync(10 * 60_000)
            } else {
                jest.setSystemTime(Date.now() + 2000)
                expect(events).toEqual([])
            }
            expect(reads).toHaveLength(2)

            controller.setForeground(true)
            expect(events).toEqual(['background_stopped', 'foreground_resumed'])
            expect(reads).toHaveLength(3)
        }
    )

    test('reads slow to once a minute after 10 minutes without a user action, and a pull resets them', async () => {
        controller.setVisible(true)
        await answer({ data: 'a', complete: true })
        for (let minute = 0.5; minute <= 10; minute += 0.5) {
            await jest.advanceTimersByTimeAsync(30_000)
            await answer({ data: 'a', complete: true })
        }
        expect(reads).toHaveLength(21)

        await jest.advanceTimersByTimeAsync(30_000)
        expect(reads).toHaveLength(21)
        await jest.advanceTimersByTimeAsync(30_000)
        expect(reads).toHaveLength(22)
        await answer({ data: 'b', complete: true })

        void controller.refresh()
        expect(reads).toHaveLength(23)
        await answer({ data: 'c', complete: true })
        await jest.advanceTimersByTimeAsync(30_000)
        expect(reads).toHaveLength(24)
    })

    test('a failed read keeps the last data and shows reconnecting until a read completes', async () => {
        controller.setVisible(true)
        await answer({ data: 'a', complete: true })
        expect(liveStatus(controller.current)).toBe('live')

        await jest.advanceTimersByTimeAsync(30_000)
        await answer(new Error('offline'))
        expect(controller.current).toMatchObject({ data: 'a', failures: 1 })
        expect(liveStatus(controller.current)).toBe('reconnecting')

        await jest.advanceTimersByTimeAsync(30_000)
        await answer({ data: 'b', complete: false })
        expect(controller.current).toMatchObject({ data: 'b', failures: 2 })
        expect(liveStatus(controller.current)).toBe('reconnecting')

        await jest.advanceTimersByTimeAsync(30_000)
        await answer({ data: 'c', complete: true })
        expect(liveStatus(controller.current)).toBe('live')
    })
})
