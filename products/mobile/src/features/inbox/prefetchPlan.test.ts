import {
    createPrefetchQueue,
    INITIAL_PREFETCH_COUNT,
    PREFETCH_CONCURRENCY,
    PREFETCH_LOOKAHEAD,
    prefetchRows,
    prefetchWindow,
} from './prefetchPlan'

const ids = (count: number): string[] => Array.from({ length: count }, (_, index) => `r${index}`)

interface Deferred {
    resolve: () => void
    reject: (error: Error) => void
}

function controlledRun(): { run: (id: string) => Promise<void>; started: string[]; settle: Map<string, Deferred> } {
    const started: string[] = []
    const settle = new Map<string, Deferred>()
    const run = (id: string): Promise<void> => {
        started.push(id)
        return new Promise<void>((resolve, reject) => settle.set(id, { resolve, reject }))
    }
    return { run, started, settle }
}

const flush = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))

describe('prefetchPlan', () => {
    const deep = INITIAL_PREFETCH_COUNT + 10
    test.each<[string, number, number | null, number]>([
        ['no viewability event yet', deep * 2, null, INITIAL_PREFETCH_COUNT],
        ['a small visible index keeps the initial count', deep * 2, 2, INITIAL_PREFETCH_COUNT],
        ['a deep visible index extends past it by the lookahead', deep * 2, deep, deep + PREFETCH_LOOKAHEAD + 1],
        ['a short list is not overrun', 3, 2, 3],
    ])('prefetchWindow: %s', (_name, length, lastVisible, expectedCount) => {
        expect(prefetchWindow(ids(length), lastVisible)).toEqual(ids(length).slice(0, expectedCount))
    })

    test('prefetchRows skips done and dismissed rows and maps list rows onto the remaining ids', () => {
        const rows = prefetchRows([
            { reportId: 'a', state: 'done' },
            { reportId: 'b', state: 'open' },
            { reportId: 'c', state: 'dismissed' },
            { reportId: 'd', state: 'snoozed' },
        ])
        expect(rows).toEqual({ ids: ['b', 'd'], idIndexByRow: [-1, 0, 0, 1] })
    })

    test('queue runs an id once while it is pending or running, and again after its run settles', async () => {
        const { run, started, settle } = controlledRun()
        const queue = createPrefetchQueue(run)
        queue.enqueue(ids(PREFETCH_CONCURRENCY + 1))
        queue.enqueue(ids(PREFETCH_CONCURRENCY + 1))
        expect(started).toEqual(ids(PREFETCH_CONCURRENCY))
        settle.get('r0')?.resolve()
        await flush()
        queue.enqueue(['r0'])
        expect(started).toEqual(ids(PREFETCH_CONCURRENCY + 1))
        settle.get(`r${PREFETCH_CONCURRENCY}`)?.resolve()
        settle.get('r1')?.resolve()
        await flush()
        expect(started).toEqual([...ids(PREFETCH_CONCURRENCY + 1), 'r0'])
    })

    test('queue starts at most the concurrency limit until a run settles', async () => {
        const { run, started, settle } = controlledRun()
        createPrefetchQueue(run).enqueue(ids(5))
        expect(started).toEqual(ids(PREFETCH_CONCURRENCY))
        settle.get('r0')?.resolve()
        await flush()
        expect(started).toEqual(ids(PREFETCH_CONCURRENCY + 1))
    })

    test('queue starts the next run after a rejected one', async () => {
        const { run, started, settle } = controlledRun()
        createPrefetchQueue(run).enqueue(ids(PREFETCH_CONCURRENCY + 1))
        settle.get('r0')?.reject(new Error('offline'))
        await flush()
        expect(started).toContain(`r${PREFETCH_CONCURRENCY}`)
    })

    test('queue reset drops the pending ids and lets the runs in flight finish', async () => {
        const { run, started, settle } = controlledRun()
        const queue = createPrefetchQueue(run)
        queue.enqueue(ids(PREFETCH_CONCURRENCY + 1))
        queue.reset()
        queue.enqueue(['x'])
        for (const id of ids(PREFETCH_CONCURRENCY)) {
            settle.get(id)?.resolve()
        }
        await flush()
        expect(started).toEqual([...ids(PREFETCH_CONCURRENCY), 'x'])
    })
})
