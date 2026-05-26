import { describe, expect, it, vi } from 'vitest'

import { ElicitationGateway } from '@/hono/session-bus/elicitation-gateway'
import type { TransportMessageSender } from '@/hono/session-bus/elicitation-gateway'
import {
    ElicitationNotSupportedError,
    SessionBusTimeoutError,
    SessionBusUnhealthyError,
} from '@/hono/session-bus/errors'
import { InMemorySessionResponseBus } from '@/hono/session-bus/in-memory-bus'

function createCapturingSender(): TransportMessageSender & { sent: unknown[] } {
    const sent: unknown[] = []
    return {
        sent,
        async send(message) {
            sent.push(message)
        },
    }
}

describe('ElicitationGateway', () => {
    it('sends a JSONRPC elicitation/create request, then resolves on a matching bus delivery', async () => {
        const bus = new InMemorySessionResponseBus()
        const sender = createCapturingSender()
        const gateway = new ElicitationGateway(bus, sender)

        const pending = gateway.elicit({
            message: 'Confirm action',
            requestedSchema: { type: 'object', properties: {} },
        })

        await new Promise((resolve) => setImmediate(resolve))
        expect(sender.sent).toHaveLength(1)
        const sent = sender.sent[0] as { id: string; method: string; jsonrpc: string }
        expect(sent.method).toBe('elicitation/create')
        expect(sent.jsonrpc).toBe('2.0')
        expect(typeof sent.id).toBe('string')

        await bus.deliver(sent.id, { action: 'accept', content: {} })

        await expect(pending).resolves.toEqual({ action: 'accept', content: {} })
    })

    it('passes through SessionBusTimeoutError on deadline', async () => {
        const bus = new InMemorySessionResponseBus()
        const sender = createCapturingSender()
        const gateway = new ElicitationGateway(bus, sender, { defaultTimeoutMs: 25 })

        await expect(
            gateway.elicit({
                message: 'x',
                requestedSchema: { type: 'object', properties: {} },
            })
        ).rejects.toBeInstanceOf(SessionBusTimeoutError)
    })

    it('rejects malformed elicit payloads with SessionBusUnhealthyError', async () => {
        const bus = new InMemorySessionResponseBus()
        const sender = createCapturingSender()
        const gateway = new ElicitationGateway(bus, sender)

        const pending = gateway.elicit({
            message: 'x',
            requestedSchema: { type: 'object', properties: {} },
        })

        await new Promise((resolve) => setImmediate(resolve))
        const sent = sender.sent[0] as { id: string }
        await bus.deliver(sent.id, { not: 'a valid ElicitResult' })

        await expect(pending).rejects.toBeInstanceOf(SessionBusUnhealthyError)
    })

    it('forwards the AbortSignal to the bus', async () => {
        const bus = new InMemorySessionResponseBus()
        const sender = createCapturingSender()
        const gateway = new ElicitationGateway(bus, sender)

        const controller = new AbortController()
        const pending = gateway.elicit(
            { message: 'x', requestedSchema: { type: 'object', properties: {} } },
            { signal: controller.signal }
        )

        controller.abort()
        await expect(pending).rejects.toThrow(/aborted/i)
    })

    it('throws ElicitationNotSupportedError when the client returns a JSON-RPC error envelope', async () => {
        const bus = new InMemorySessionResponseBus()
        const sender = createCapturingSender()
        const gateway = new ElicitationGateway(bus, sender)

        const pending = gateway.elicit({
            message: 'x',
            requestedSchema: { type: 'object', properties: {} },
        })

        await new Promise((resolve) => setImmediate(resolve))
        const sent = sender.sent[0] as { id: string }
        await bus.deliver(sent.id, { error: { code: -32601, message: 'Method not found' } })

        let caught: unknown
        try {
            await pending
        } catch (e) {
            caught = e
        }
        expect(caught).toBeInstanceOf(ElicitationNotSupportedError)
        expect((caught as ElicitationNotSupportedError).code).toBe(-32601)
    })

    it('invokes onNotSupported metric when the client signals lack of support', async () => {
        const bus = new InMemorySessionResponseBus()
        const sender = createCapturingSender()
        const notSupportedSpy = vi.fn()
        const gateway = new ElicitationGateway(bus, sender, {
            metrics: { onNotSupported: notSupportedSpy },
        })

        const pending = gateway.elicit({
            message: 'x',
            requestedSchema: { type: 'object', properties: {} },
        })

        await new Promise((resolve) => setImmediate(resolve))
        const sent = sender.sent[0] as { id: string }
        await bus.deliver(sent.id, { error: { code: -32602, message: 'unsupported mode' } })

        await expect(pending).rejects.toBeInstanceOf(ElicitationNotSupportedError)
        expect(notSupportedSpy).toHaveBeenCalledTimes(1)
        expect(notSupportedSpy).toHaveBeenCalledWith(expect.any(String), -32602)
    })

    it('emits await-start / resolve metrics via the configured hook', async () => {
        const bus = new InMemorySessionResponseBus()
        const sender = createCapturingSender()
        const startSpy = vi.fn()
        const resolveSpy = vi.fn()
        const gateway = new ElicitationGateway(bus, sender, {
            metrics: { onAwaitStart: startSpy, onResolve: resolveSpy },
        })

        const pending = gateway.elicit({
            message: 'x',
            requestedSchema: { type: 'object', properties: {} },
        })

        await new Promise((resolve) => setImmediate(resolve))
        const sent = sender.sent[0] as { id: string }
        await bus.deliver(sent.id, { action: 'cancel' })
        await pending

        expect(startSpy).toHaveBeenCalledTimes(1)
        expect(resolveSpy).toHaveBeenCalledTimes(1)
    })
})
