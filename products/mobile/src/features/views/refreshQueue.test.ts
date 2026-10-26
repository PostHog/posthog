import type { BudgetFamily } from '@/api/budget'
import { ApiError } from '@/api/client'

import { type JobRequest, type ReadResult, RefreshQueue } from './refreshQueue'

interface Deferred {
    resolve: (result: ReadResult) => void
    reject: (error: unknown) => void
}

describe('RefreshQueue', () => {
    let now = 0
    let calls: { key: string; mode: string }[] = []
    let pending: Map<string, Deferred>
    let spendable: Record<BudgetFamily, boolean>
    let queue: RefreshQueue

    function request(key: string, overrides: Partial<JobRequest> = {}): JobRequest {
        return {
            key,
            family: 'insights',
            group: 'list',
            mode: 'blocking',
            run: (mode) => {
                calls.push({ key, mode })
                return new Promise<ReadResult>((resolve, reject) => pending.set(key, { resolve, reject }))
            },
            ...overrides,
        }
    }

    async function settle(key: string, result: ReadResult | Error): Promise<void> {
        const deferred = pending.get(key)
        pending.delete(key)
        if (result instanceof Error) {
            deferred?.reject(result)
        } else {
            deferred?.resolve(result)
        }
        for (let tick = 0; tick < 5; tick += 1) {
            await Promise.resolve()
        }
    }

    const OK: ReadResult = { status: 'ok', computed: true }

    beforeEach(() => {
        jest.useFakeTimers()
        now = 1_000_000
        calls = []
        pending = new Map()
        spendable = { insights: true, dashboards: true, query: true, replay: true }
        queue = new RefreshQueue({ now: () => now, canSpend: (family) => spendable[family] })
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    test('runs two requests at a time and joins a second caller for the same key', async () => {
        const first = queue.enqueue(request('a'))
        const joined = queue.enqueue(request('a', { group: 'dashboard:1', mode: 'force_blocking', userRetry: true }))
        void queue.enqueue(request('b'))
        void queue.enqueue(request('c'))

        expect(calls.map((call) => call.key)).toEqual(['a', 'b'])
        await settle('a', OK)

        expect(calls.map((call) => call.key)).toEqual(['a', 'b', 'c'])
        expect(joined).toBe(first)
        await expect(first).resolves.toMatchObject({ status: 'ok', computed: true })
    })

    test('skips an item asked for again within a minute of its last request, unless a person retries it', async () => {
        const first = queue.enqueue(request('a'))
        await settle('a', OK)
        await first

        now += 59_000
        await expect(queue.enqueue(request('a'))).resolves.toMatchObject({ status: 'skipped' })
        now += 1_000
        void queue.enqueue(request('a'))
        expect(calls).toHaveLength(2)

        await settle('a', new Error('Network request failed'))
        void queue.enqueue(request('a', { userRetry: true }))
        expect(calls).toHaveLength(3)
    })

    test('pauses only the family that answered 429 for its Retry-After', async () => {
        const failed = queue.enqueue(request('a'))
        await settle('a', new ApiError(429, {}, { get: () => '10' } as unknown as Headers))
        await expect(failed).resolves.toMatchObject({ status: 'failed' })

        void queue.enqueue(request('b', { userRetry: true }))
        void queue.enqueue(request('d', { family: 'dashboards' }))
        expect(calls.map((call) => call.key)).toEqual(['a', 'd'])

        now += 10_000
        jest.advanceTimersByTime(10_000)
        expect(calls.map((call) => call.key)).toEqual(['a', 'd', 'b'])
    })

    test('reschedules for a newly paused family with an earlier deadline', async () => {
        void queue.enqueue(request('a'))
        void queue.enqueue(request('b', { family: 'dashboards' }))
        await settle('a', new ApiError(429, {}, { get: () => '30' } as unknown as Headers))
        await settle('b', new ApiError(429, {}, { get: () => '10' } as unknown as Headers))
        void queue.enqueue(request('c'))
        void queue.enqueue(request('d', { family: 'dashboards' }))

        now += 10_000
        jest.advanceTimersByTime(10_000)
        expect(calls.map((call) => call.key)).toEqual(['a', 'b', 'd'])

        now += 20_000
        jest.advanceTimersByTime(20_000)
        expect(calls.map((call) => call.key)).toEqual(['a', 'b', 'd', 'c'])
    })

    test('a stalled read fails at its deadline and frees a slot for a queued read', async () => {
        let signal: AbortSignal | undefined
        const limited = new RefreshQueue({
            maxInFlight: 1,
            requestDeadlineMs: 5_000,
            now: () => now,
            canSpend: () => true,
        })
        const stalled = limited.enqueue(
            request('a', {
                run: (mode, abortSignal) => {
                    calls.push({ key: 'a', mode })
                    signal = abortSignal
                    return new Promise<ReadResult>(() => undefined)
                },
            })
        )
        void limited.enqueue(request('b'))
        expect(calls.map((call) => call.key)).toEqual(['a'])

        now += 5_000
        jest.advanceTimersByTime(5_000)
        await expect(stalled).resolves.toMatchObject({ status: 'failed' })
        expect(signal?.aborted).toBe(true)
        expect(calls.map((call) => call.key)).toEqual(['a', 'b'])
    })

    test('retries a rate-limited read once after 5 s, then reports it failed', async () => {
        const result = queue.enqueue(request('a'))
        await settle('a', { status: 'rate_limited', computed: false })
        expect(calls).toHaveLength(1)
        expect(queue.isBusy('list')).toBe(true)

        jest.advanceTimersByTime(5_000)
        expect(calls).toHaveLength(2)
        await settle('a', { status: 'rate_limited', computed: false })

        await expect(result).resolves.toMatchObject({ status: 'failed' })
        expect(queue.isBusy('list')).toBe(false)
    })

    test.each([false, true])('sends nothing when the family budget is empty, user request: %s', async (userRetry) => {
        spendable.insights = false

        await expect(queue.enqueue(request('a', { userRetry }))).resolves.toMatchObject({
            status: 'capped',
            family: 'insights',
        })
        expect(calls).toHaveLength(0)
    })

    test('drops the queued jobs of a screen that left and lets its running reads finish', async () => {
        let signal: AbortSignal | undefined
        const running = queue.enqueue(
            request('a', {
                run: (mode, abortSignal) => {
                    signal = abortSignal
                    calls.push({ key: 'a', mode })
                    return new Promise<ReadResult>((resolve, reject) => pending.set('a', { resolve, reject }))
                },
            })
        )
        void queue.enqueue(request('b'))
        const queued = queue.enqueue(request('c'))
        const shared = queue.enqueue(request('b', { group: 'insight:x' }))

        queue.leave('list')

        expect(signal?.aborted).toBe(false)
        await expect(queued).resolves.toMatchObject({ status: 'aborted' })
        // The screen comes back while the server still computes: it joins the running read.
        expect(queue.enqueue(request('a'))).toBe(running)
        await settle('a', OK)
        await expect(running).resolves.toMatchObject({ status: 'ok' })
        await settle('b', OK)
        await expect(shared).resolves.toMatchObject({ status: 'ok' })

        // The finished read keeps its minute, so a return right after it sends nothing.
        await expect(queue.enqueue(request('a'))).resolves.toMatchObject({ status: 'skipped' })
        expect(calls.map((call) => call.key)).toEqual(['a', 'b'])
    })
})
