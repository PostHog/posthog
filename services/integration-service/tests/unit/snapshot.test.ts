import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Lifecycle } from '@/http/app'
import { logger } from '@/lib/logging'
import { scheduleJittered } from '@/lib/schedule'
import { register, servingStaleSeconds } from '@/metrics'
import { SnapshotManager } from '@/snapshot'
import type { SecretStore } from '@/store/fileStore'
import type { SecretsSnapshot } from '@/types'

const NOW = Date.parse('2026-08-10T12:00:00.000Z')

function snapshot(fetchedAt: string): SecretsSnapshot {
    return {
        fetchedAt,
        versionId: 'v1',
        changedAt: '2026-08-01T00:00:00.000Z',
        secrets: { HUBSPOT_APP_CLIENT_SECRET: { state: 'steady', value: 's', versionId: 'v1', fetchedAt } },
    }
}

/** A store whose loads answer from a queue, repeating the last entry when it runs out. */
function queuedStore(results: (SecretsSnapshot | null)[]): SecretStore {
    const queue = [...results]
    return { load: () => Promise.resolve(queue.length > 1 ? (queue.shift() ?? null) : (queue[0] ?? null)) }
}

function manager(
    store: SecretStore,
    lifecycle: Lifecycle = { shuttingDown: false, ready: false }
): { manager: SnapshotManager; lifecycle: Lifecycle } {
    return { manager: new SnapshotManager({ store, lifecycle, dir: '/mnt', now: () => NOW }), lifecycle }
}

describe('snapshot manager', () => {
    beforeEach(() => {
        register.resetMetrics()
    })

    afterEach(() => {
        vi.restoreAllMocks()
    })

    it('keeps serving the previous snapshot when a reload returns nothing', async () => {
        const held = snapshot('2026-08-10T11:00:00.000Z')
        const { manager: m, lifecycle } = manager(queuedStore([held, null]))

        await m.reload()
        await m.reload()

        expect(m.current()).toBe(held)
        expect(lifecycle.ready).toBe(true)
        // An hour old, and the gauge says so rather than the degradation being silent.
        const stale = (await servingStaleSeconds.get()).values[0]?.value
        expect(stale).toBe(3600)
    })

    it('resets the staleness gauge once the mount reads again', async () => {
        const { manager: m } = manager(
            queuedStore([snapshot('2026-08-10T11:00:00.000Z'), null, snapshot(new Date(NOW).toISOString())])
        )

        await m.reload()
        await m.reload()
        await m.reload()

        expect((await servingStaleSeconds.get()).values[0]?.value).toBe(0)
    })

    it('recovers readiness once a mount appears, without ever crashing', async () => {
        const { manager: m, lifecycle } = manager(queuedStore([null, snapshot('2026-08-10T11:59:00.000Z')]))

        await m.reload()
        expect(lifecycle.ready).toBe(false)
        expect(m.current()).toBeNull()

        await m.reload()
        expect(lifecycle.ready).toBe(true)
        expect(m.current()).not.toBeNull()
    })

    it('logs snapshot_lost only on the ready-to-not-ready transition', async () => {
        const error = vi.spyOn(logger, 'error')

        // Marked ready with no snapshot held: the one state where the pod goes not-ready.
        const { manager: lost } = manager(queuedStore([null]), { shuttingDown: false, ready: true })
        await lost.reload()
        expect(error.mock.calls.filter(([event]) => event === 'secrets:snapshot_lost')).toHaveLength(1)

        error.mockClear()

        // Never ready: same empty read, but nothing was lost.
        const { manager: starting } = manager(queuedStore([null]))
        await starting.reload()
        await starting.reload()
        expect(error.mock.calls.filter(([event]) => event === 'secrets:snapshot_lost')).toHaveLength(0)
    })
})

describe('scheduleJittered', () => {
    beforeEach(() => {
        vi.useFakeTimers()
    })

    afterEach(() => {
        vi.useRealTimers()
        vi.restoreAllMocks()
    })

    it('re-draws the delay each tick and never exceeds the configured interval', async () => {
        const runs: number[] = []
        const task = (): Promise<void> => {
            runs.push(Date.now())
            return Promise.resolve()
        }

        // Worst-case draw first: the delay must cap at the full interval, not 1.5x it.
        // The next draw happens when the first tick re-arms, so queue it up front.
        vi.spyOn(Math, 'random').mockReturnValueOnce(1).mockReturnValue(0)
        const start = Date.now()
        const cancel = scheduleJittered(10_000, task)

        await vi.advanceTimersByTimeAsync(10_000)
        expect(runs).toEqual([start + 10_000])

        // Best-case draw next: a fresh jitter per tick, not the first delay forever.
        await vi.advanceTimersByTimeAsync(5_000)
        expect(runs).toEqual([start + 10_000, start + 15_000])

        cancel()
    })

    it('stops re-arming once cancelled', async () => {
        const task = vi.fn().mockResolvedValue(undefined)
        vi.spyOn(Math, 'random').mockReturnValue(0)

        const cancel = scheduleJittered(10_000, task)
        await vi.advanceTimersByTimeAsync(5_000)
        expect(task).toHaveBeenCalledTimes(1)

        cancel()
        await vi.advanceTimersByTimeAsync(30_000)
        expect(task).toHaveBeenCalledTimes(1)
    })
})
