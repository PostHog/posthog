import { describe, expect, it } from 'vitest'

import { SessionBusAbortedError, SessionBusTimeoutError } from '@/hono/session-bus/errors'
import { InMemorySessionResponseBus } from '@/hono/session-bus/in-memory-bus'

describe('InMemorySessionResponseBus', () => {
    it('resolves an awaiter when a matching deliver lands', async () => {
        const bus = new InMemorySessionResponseBus()
        const pending = bus.await('session-a', 'req-1', { timeoutMs: 1_000 })
        await bus.deliver('session-a', 'req-1', { action: 'accept' })
        await expect(pending).resolves.toEqual({ action: 'accept' })
    })

    it('resolves an awaiter that registers AFTER an early delivery', async () => {
        const bus = new InMemorySessionResponseBus()
        await bus.deliver('session-a', 'req-1', { action: 'decline' })
        await expect(bus.await('session-a', 'req-1', { timeoutMs: 1_000 })).resolves.toEqual({
            action: 'decline',
        })
    })

    it('does not cross deliveries between different request ids', async () => {
        // The bus correlates by JSONRPC request id alone — sessionId is
        // accepted for API symmetry but ignored in the key. Document the
        // actual contract: same requestId resolves regardless of sessionId.
        const bus = new InMemorySessionResponseBus()
        const pending = bus.await('session-a', 'req-1', { timeoutMs: 100 })
        await bus.deliver('session-a', 'req-2', { action: 'accept' })
        await expect(pending).rejects.toBeInstanceOf(SessionBusTimeoutError)
    })

    it('resolves regardless of sessionId mismatch (request id is the correlation key)', async () => {
        const bus = new InMemorySessionResponseBus()
        const pending = bus.await('session-a', 'req-1', { timeoutMs: 1_000 })
        await bus.deliver('session-b', 'req-1', { action: 'accept' })
        await expect(pending).resolves.toEqual({ action: 'accept' })
    })

    it('times out with SessionBusTimeoutError when no deliver arrives', async () => {
        const bus = new InMemorySessionResponseBus()
        await expect(bus.await('s', 'r', { timeoutMs: 25 })).rejects.toBeInstanceOf(SessionBusTimeoutError)
    })

    it('rejects with SessionBusAbortedError when the signal aborts during await', async () => {
        const bus = new InMemorySessionResponseBus()
        const controller = new AbortController()
        const pending = bus.await('s', 'r', { timeoutMs: 5_000, signal: controller.signal })
        controller.abort()
        await expect(pending).rejects.toBeInstanceOf(SessionBusAbortedError)
    })

    it('rejects immediately if the signal is already aborted before await', async () => {
        const bus = new InMemorySessionResponseBus()
        const controller = new AbortController()
        controller.abort()
        await expect(bus.await('s', 'r', { timeoutMs: 5_000, signal: controller.signal })).rejects.toBeInstanceOf(
            SessionBusAbortedError
        )
    })

    it('refuses concurrent awaits on the same key', async () => {
        const bus = new InMemorySessionResponseBus()
        // Start the first await; intentionally don't await it so it stays parked.
        void bus.await('s', 'r', { timeoutMs: 1_000 }).catch(() => undefined)
        await expect(bus.await('s', 'r', { timeoutMs: 1_000 })).rejects.toThrow(/Concurrent await/)
    })

    it('invokes resolve metric with elapsed latency', async () => {
        const bus = new InMemorySessionResponseBus()
        let observedLatency: number | undefined
        const pending = bus.await('s', 'r', {
            timeoutMs: 1_000,
            metrics: { onResolve: (_s, _r, ms) => (observedLatency = ms) },
        })
        await bus.deliver('s', 'r', { action: 'accept' })
        await pending
        expect(observedLatency).toBeGreaterThanOrEqual(0)
        expect(observedLatency).toBeLessThan(50)
    })

    it('invokes timeout metric exactly once on deadline', async () => {
        const bus = new InMemorySessionResponseBus()
        let timeouts = 0
        await expect(
            bus.await('s', 'r', {
                timeoutMs: 10,
                metrics: { onTimeout: () => timeouts++ },
            })
        ).rejects.toBeInstanceOf(SessionBusTimeoutError)
        expect(timeouts).toBe(1)
    })

    it('aborts all parked awaits on shutdown', async () => {
        const bus = new InMemorySessionResponseBus()
        const a = bus.await('s', 'r1', { timeoutMs: 5_000 })
        const b = bus.await('s', 'r2', { timeoutMs: 5_000 })
        bus.abortAll('shutdown')
        await expect(a).rejects.toBeInstanceOf(SessionBusAbortedError)
        await expect(b).rejects.toBeInstanceOf(SessionBusAbortedError)
        expect(bus.parkedCount()).toBe(0)
    })

    it('clears the parked entry after a one-shot deliver', async () => {
        const bus = new InMemorySessionResponseBus()
        const pending = bus.await('s', 'r', { timeoutMs: 1_000 })
        await bus.deliver('s', 'r', { action: 'accept' })
        await pending
        expect(bus.parkedCount()).toBe(0)
    })
})
