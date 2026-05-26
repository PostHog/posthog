import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { RedisLike } from '@/hono/cache/RedisCache'
import { createAdaptivePollSchedule } from '@/hono/session-bus/adaptive-poll'
import { SessionBusAbortedError, SessionBusTimeoutError, SessionBusUnhealthyError } from '@/hono/session-bus/errors'
import { RedisPollingSessionResponseBus } from '@/hono/session-bus/redis-polling-bus'

interface MockRedis extends RedisLike {
    _store: Map<string, string>
    _failNextN: { get: number; set: number }
}

function createMockRedis(): MockRedis {
    const store = new Map<string, string>()
    const failNextN = { get: 0, set: 0 }
    return {
        get: vi.fn(async (key: string) => {
            if (failNextN.get > 0) {
                failNextN.get--
                throw new Error('mock redis get failure')
            }
            return store.get(key) ?? null
        }),
        set: vi.fn(async (key: string, value: string, ..._args: (string | number)[]) => {
            if (failNextN.set > 0) {
                failNextN.set--
                throw new Error('mock redis set failure')
            }
            // Honor NX semantics: if the key already exists, refuse the write
            // and return null. Required for testing the first-writer-wins
            // bus contract.
            const args = _args.map((a) => (typeof a === 'string' ? a.toUpperCase() : a))
            const nx = args.includes('NX')
            if (nx && store.has(key)) {
                return null
            }
            store.set(key, value)
            return 'OK'
        }),
        del: vi.fn(async (...keys: string[]) => {
            let count = 0
            for (const key of keys) {
                if (store.delete(key)) {
                    count++
                }
            }
            return count
        }),
        scan: vi.fn(async () => ['0', []] as [string, string[]]),
        incr: vi.fn(async () => 1),
        expire: vi.fn(async () => 1),
        ttl: vi.fn(async () => -1),
        _store: store,
        _failNextN: failNextN,
    }
}

/** Schedule with very short delays so tests don't take seconds. */
const FAST_SCHEDULE = createAdaptivePollSchedule({
    hotIntervalMs: 5,
    coolIntervalMs: 10,
    hotWindowMs: 50,
})

describe('RedisPollingSessionResponseBus', () => {
    let redis: MockRedis
    let bus: RedisPollingSessionResponseBus

    beforeEach(() => {
        redis = createMockRedis()
        bus = new RedisPollingSessionResponseBus(redis, {
            schedule: FAST_SCHEDULE,
            responseTtlSeconds: 60,
        })
    })

    it('resolves when a deliver lands on the same instance', async () => {
        const pending = bus.await('r', { timeoutMs: 1_000 })
        await bus.deliver('r', { action: 'accept' })
        await expect(pending).resolves.toEqual({ action: 'accept' })
    })

    it('resolves when a deliver writes the underlying key directly', async () => {
        const pending = bus.await('r', { timeoutMs: 1_000 })
        await new Promise((resolve) => setTimeout(resolve, 10))
        redis._store.set('mcp:session-response:r', JSON.stringify({ action: 'decline' }))
        await expect(pending).resolves.toEqual({ action: 'decline' })
    })

    it('first deliver wins; a second deliver for the same key is silently dropped', async () => {
        // First-writer-wins is the bus contract. SET NX in the implementation
        // makes the second SET a no-op. This protects against duplicate POSTs
        // (network retry, user double-click with a different choice, or an
        // attacker racing replies).
        await bus.deliver('r', { action: 'accept', content: { first: true } })
        await bus.deliver('r', { action: 'decline', content: { second: true } })
        const pending = bus.await<{ action: string; content: Record<string, unknown> }>('r', {
            timeoutMs: 1_000,
        })
        const result = await pending
        expect(result.action).toBe('accept')
        expect(result.content).toEqual({ first: true })
    })

    it('DELs the key after a successful read (one-shot)', async () => {
        const pending = bus.await('r', { timeoutMs: 1_000 })
        await bus.deliver('r', { action: 'accept' })
        await pending
        await new Promise((resolve) => setTimeout(resolve, 10))
        expect(redis._store.has('mcp:session-response:r')).toBe(false)
    })

    it('times out when no deliver arrives within the deadline', async () => {
        await expect(bus.await('r', { timeoutMs: 30 })).rejects.toBeInstanceOf(SessionBusTimeoutError)
    })

    it('aborts immediately when signal is already aborted before await', async () => {
        const controller = new AbortController()
        controller.abort()
        await expect(bus.await('r', { timeoutMs: 1_000, signal: controller.signal })).rejects.toBeInstanceOf(
            SessionBusAbortedError
        )
    })

    it('aborts mid-poll when signal fires later', async () => {
        const controller = new AbortController()
        const pending = bus.await('r', { timeoutMs: 5_000, signal: controller.signal })
        setTimeout(() => controller.abort(), 20)
        await expect(pending).rejects.toBeInstanceOf(SessionBusAbortedError)
    })

    it('tolerates transient redis errors and eventually resolves', async () => {
        redis._failNextN.get = 3
        const pending = bus.await('r', { timeoutMs: 1_000 })
        setTimeout(() => {
            void bus.deliver('r', { action: 'accept' })
        }, 60)
        await expect(pending).resolves.toEqual({ action: 'accept' })
    })

    it('fails with SessionBusUnhealthyError after consecutive redis errors', async () => {
        redis._failNextN.get = 99
        const tightBus = new RedisPollingSessionResponseBus(redis, {
            schedule: FAST_SCHEDULE,
            maxConsecutiveErrors: 3,
        })
        await expect(tightBus.await('r', { timeoutMs: 5_000 })).rejects.toBeInstanceOf(SessionBusUnhealthyError)
    })

    it('treats invalid JSON in stored payload as bus unhealthy', async () => {
        const pending = bus.await('r', { timeoutMs: 1_000 })
        redis._store.set('mcp:session-response:r', '{not-json')
        await expect(pending).rejects.toBeInstanceOf(SessionBusUnhealthyError)
    })

    it('translates SET failure into SessionBusUnhealthyError', async () => {
        redis._failNextN.set = 1
        await expect(bus.deliver('r', { action: 'accept' })).rejects.toBeInstanceOf(SessionBusUnhealthyError)
    })

    it('emits the documented metric signals on the happy path', async () => {
        const events: string[] = []
        const pending = bus.await('r', {
            timeoutMs: 1_000,
            metrics: {
                onAwaitStart: () => events.push('start'),
                onPoll: () => events.push('poll'),
                onResolve: () => events.push('resolve'),
            },
        })
        await bus.deliver('r', { action: 'accept' })
        await pending
        expect(events[0]).toBe('start')
        expect(events).toContain('poll')
        expect(events[events.length - 1]).toBe('resolve')
    })

    it('uses adaptive polling cadence (more polls early than late)', async () => {
        const events: number[] = []
        const start = Date.now()
        const pending = bus.await('r', {
            timeoutMs: 200,
            metrics: { onPoll: () => events.push(Date.now() - start) },
        })
        await expect(pending).rejects.toBeInstanceOf(SessionBusTimeoutError)
        expect(events.length).toBeGreaterThan(2)
    })
})
