import { describe, expect, it } from 'vitest'

import { ElicitBinding } from '@/hono/elicit-binding'
import { InMemorySessionResponseBus } from '@/hono/session-bus/in-memory-bus'
import { createSseResponse } from '@/hono/sse-response'

describe('ElicitBinding (integration with bus + SSE)', () => {
    it('lazy-creates the SSE handle only when invoke() is first called', async () => {
        const bus = new InMemorySessionResponseBus()
        let createCount = 0
        const binding = new ElicitBinding({
            bus,
            createSseHandle: async () => {
                createCount++
                return createSseResponse()
            },
        })
        expect(createCount).toBe(0)
        expect(binding.getSseHandle()).toBeUndefined()
    })

    it('resolves firstElicit and exposes the SSE handle on the first invoke', async () => {
        const bus = new InMemorySessionResponseBus()
        const binding = new ElicitBinding({
            bus,
            createSseHandle: async () => createSseResponse(),
        })

        let firstElicitResolved = false
        void binding.firstElicit.then(() => {
            firstElicitResolved = true
        })

        // Kick off the elicit. Don't await — it parks on the bus.
        const elicitPromise = binding.invoke({
            message: 'Confirm',
            requestedSchema: { type: 'object', properties: {} },
        })

        await binding.firstElicit
        expect(firstElicitResolved).toBe(true)
        const handle = binding.getSseHandle()
        expect(handle).not.toBeUndefined()

        // The elicit message must already be on the SSE stream.
        // Resolve the elicit so the parked promise can finish.
        const reader = createSseReader(handle!.response)
        const elicitMessage = (await reader.next()) as { id: string; method: string }
        expect(elicitMessage.method).toBe('elicitation/create')
        expect(typeof elicitMessage.id).toBe('string')

        await bus.deliver(elicitMessage.id, { action: 'accept' })
        await expect(elicitPromise).resolves.toEqual({ action: 'accept' })

        // Close so any readers don't hang.
        await handle!.writer.close()
    })

    it('serializes multiple elicits through the same SSE writer', async () => {
        const bus = new InMemorySessionResponseBus()
        const binding = new ElicitBinding({
            bus,
            createSseHandle: async () => createSseResponse(),
        })

        // Stream the SSE body as messages flow. We need a single reader for
        // the whole test because Response bodies are not re-readable.
        const elicit1 = binding.invoke({
            message: 'First',
            requestedSchema: { type: 'object', properties: {} },
        })
        await binding.firstElicit
        const handle = binding.getSseHandle()!
        const reader = createSseReader(handle.response)

        const first = await reader.next()
        const id1 = (first as { id: string }).id
        await bus.deliver(id1, { action: 'accept' })
        await expect(elicit1).resolves.toEqual({ action: 'accept' })

        const elicit2 = binding.invoke({
            message: 'Second',
            requestedSchema: { type: 'object', properties: {} },
        })
        const second = await reader.next()
        const id2 = (second as { id: string }).id
        expect(id2).not.toBe(id1)

        await bus.deliver(id2, { action: 'decline' })
        await expect(elicit2).resolves.toEqual({ action: 'decline' })

        await handle.writer.close()
    })

    it('propagates requestSignal abort into pending elicit awaits', async () => {
        const bus = new InMemorySessionResponseBus()
        const controller = new AbortController()
        const binding = new ElicitBinding({
            bus,
            createSseHandle: async () => createSseResponse(),
            requestSignal: controller.signal,
        })

        const elicit = binding.invoke({
            message: 'Confirm',
            requestedSchema: { type: 'object', properties: {} },
        })

        controller.abort()
        await expect(elicit).rejects.toThrow(/aborted/i)
    })
})

/**
 * Read SSE frames from a Response body one at a time. Holds the underlying
 * reader open across `next()` calls — important for tests that interleave
 * elicit deliveries with reads.
 */
function createSseReader(response: Response): { next: () => Promise<unknown> } {
    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    return {
        async next(): Promise<unknown> {
            while (!buffer.includes('\n\n')) {
                const { value, done } = await reader.read()
                if (done) {
                    throw new Error('SSE stream closed before next frame')
                }
                buffer += decoder.decode(value, { stream: true })
            }
            const splitAt = buffer.indexOf('\n\n')
            const frame = buffer.slice(0, splitAt)
            buffer = buffer.slice(splitAt + 2)
            const dataLine = frame.split('\n').find((line) => line.startsWith('data: '))
            if (!dataLine) {
                throw new Error(`SSE frame missing data line: ${frame}`)
            }
            return JSON.parse(dataLine.slice('data: '.length))
        },
    }
}
