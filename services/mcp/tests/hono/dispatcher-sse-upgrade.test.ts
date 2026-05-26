import { describe, expect, it } from 'vitest'

import { ElicitBinding } from '@/hono/elicit-binding'
import { InMemorySessionResponseBus } from '@/hono/session-bus/in-memory-bus'
import { createSseResponse, type SseResponseHandle } from '@/hono/sse-response'

/**
 * Exercises the exact race + finalize pattern the dispatcher uses for the
 * `tools/call` SSE upgrade. The full `McpDispatcher.dispatchToolsCallWithMaybeSse`
 * pulls in the state resolver, API client, feature flag evaluator, and tool
 * catalog — most of which are mock-heavy and orthogonal to the SSE-upgrade
 * decision. This suite isolates the upgrade logic itself.
 *
 * Concretely, what each test verifies:
 *
 * 1. **Handler-wins path** — when the tool handler completes before any elicit
 *    fires, the dispatcher returns a plain JSON response (no SSE upgrade) and
 *    the SSE handle stays `undefined`.
 * 2. **Elicit-wins path** — when the first elicit fires before the handler
 *    completes, the dispatcher reads the SSE handle and returns the streaming
 *    Response. Subsequent finalize writes the tool result and closes the stream.
 * 3. **Tool throw on SSE path** — when the handler throws AFTER triggering an
 *    elicit, finalize still writes a JSONRPC error frame and closes the stream.
 */

interface RaceOutcome {
    kind: 'json' | 'sse'
    sseHandle?: SseResponseHandle
}

/**
 * Imitates `dispatchToolsCallWithMaybeSse`. Kept as a free function so the
 * tests can assert outcomes without spinning up a dispatcher.
 */
async function raceHandlerAgainstElicit(
    binding: ElicitBinding,
    handlerPromise: Promise<unknown>
): Promise<RaceOutcome> {
    type HandlerOutcome = { kind: 'success'; value: unknown } | { kind: 'error'; error: unknown }
    const wrappedHandler: Promise<HandlerOutcome> = handlerPromise
        .then((value): HandlerOutcome => ({ kind: 'success', value }))
        .catch((error): HandlerOutcome => ({ kind: 'error', error }))

    const winner = await Promise.race([
        wrappedHandler.then(() => 'handler' as const),
        binding.firstElicit.then(() => 'elicit' as const),
    ])

    if (winner === 'handler') {
        await wrappedHandler
        return { kind: 'json' }
    }
    const sseHandle = binding.getSseHandle()
    if (!sseHandle) {
        throw new Error('elicit won the race but no SSE handle was recorded')
    }
    return { kind: 'sse', sseHandle }
}

/**
 * Imitates `McpDispatcher.finalizeSseResponse`. Awaits the handler outcome,
 * writes the JSONRPC result/error frame, closes the SSE stream.
 */
async function finalize(sseHandle: SseResponseHandle, callId: string, handlerPromise: Promise<unknown>): Promise<void> {
    try {
        let result: unknown
        try {
            const value = await handlerPromise
            result = { jsonrpc: '2.0' as const, id: callId, result: value }
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error)
            result = { jsonrpc: '2.0' as const, id: callId, error: { code: -32603, message } }
        }
        await sseHandle.writer.write(result as Parameters<typeof sseHandle.writer.write>[0])
    } finally {
        try {
            await sseHandle.writer.close()
        } catch {
            /* already closed */
        }
    }
}

/** Read all SSE frames from a Response body. */
async function readAllFrames(response: Response): Promise<unknown[]> {
    const text = await response.clone().text()
    return text
        .split('\n\n')
        .filter(Boolean)
        .map((frame) => {
            const dataLine = frame.split('\n').find((l) => l.startsWith('data: '))
            if (!dataLine) {
                throw new Error(`SSE frame missing data line: ${frame}`)
            }
            return JSON.parse(dataLine.slice('data: '.length)) as unknown
        })
}

describe('Dispatcher SSE-upgrade race + finalize', () => {
    it('returns plain JSON when the handler completes before any elicit fires', async () => {
        const bus = new InMemorySessionResponseBus()
        const binding = new ElicitBinding({
            bus,
            createSseHandle: async () => createSseResponse(),
        })
        const handlerPromise = Promise.resolve('handler-result')

        const outcome = await raceHandlerAgainstElicit(binding, handlerPromise)

        expect(outcome.kind).toBe('json')
        expect(binding.getSseHandle()).toBeUndefined()
    })

    it('upgrades to SSE when the handler invokes elicit, then writes the final tool result frame', async () => {
        const bus = new InMemorySessionResponseBus()
        const binding = new ElicitBinding({
            bus,
            createSseHandle: async () => createSseResponse(),
        })
        const callId = 'tools-call-1'

        // Tool handler: invoke elicit, then wait for the reply, then return a tool result.
        const handlerPromise = (async (): Promise<unknown> => {
            const reply = await binding.invoke({
                message: 'Confirm',
                requestedSchema: { type: 'object', properties: {} },
            })
            return { content: [{ type: 'text', text: `reply=${reply.action}` }] }
        })()

        const outcome = await raceHandlerAgainstElicit(binding, handlerPromise)
        expect(outcome.kind).toBe('sse')
        const sseHandle = outcome.sseHandle!
        expect(sseHandle.response.headers.get('Content-Type')).toBe('text/event-stream')

        // Concurrently drive the finalize and the client reply. The order of
        // these steps mirrors what the dispatcher hands off: the SSE response
        // is already returned to the client, the handler is still running, and
        // when its bus.await resolves it writes the tool result frame.
        const finalizePromise = finalize(sseHandle, callId, handlerPromise)

        // Read the first frame off a parallel clone before the reply lands.
        const reader = sseHandle.response.body!.getReader()
        const decoder = new TextDecoder()
        let buf = ''
        async function nextFrame(): Promise<unknown> {
            while (!buf.includes('\n\n')) {
                const { value, done } = await reader.read()
                if (done) {
                    throw new Error('SSE closed before next frame')
                }
                buf += decoder.decode(value, { stream: true })
            }
            const splitAt = buf.indexOf('\n\n')
            const frame = buf.slice(0, splitAt)
            buf = buf.slice(splitAt + 2)
            const dataLine = frame.split('\n').find((l) => l.startsWith('data: '))
            return JSON.parse(dataLine!.slice('data: '.length))
        }

        const elicitFrame = (await nextFrame()) as { id: string; method: string; params: unknown }
        expect(elicitFrame.method).toBe('elicitation/create')
        expect(typeof elicitFrame.id).toBe('string')

        // Deliver the client's reply. The handler's bus.await resolves and the
        // handler completes; finalize then writes the second SSE frame.
        await bus.deliver(elicitFrame.id, { action: 'accept', content: { confirmed: true } })

        const resultFrame = (await nextFrame()) as { id: string; result?: unknown; error?: unknown }
        expect(resultFrame.id).toBe(callId)
        expect(resultFrame.result).toEqual({ content: [{ type: 'text', text: 'reply=accept' }] })

        await finalizePromise

        // Stream must be closed.
        const { done } = await reader.read()
        expect(done).toBe(true)
    })

    it('writes a JSONRPC error frame when the handler throws on the SSE path', async () => {
        const bus = new InMemorySessionResponseBus()
        const binding = new ElicitBinding({
            bus,
            createSseHandle: async () => createSseResponse(),
        })
        const callId = 'tools-call-err'

        const handlerPromise = (async (): Promise<unknown> => {
            const reply = await binding.invoke({
                message: 'Confirm',
                requestedSchema: { type: 'object', properties: {} },
            })
            if (reply.action !== 'accept') {
                throw new Error('user declined')
            }
            return { value: 'never-reached' }
        })()

        const outcome = await raceHandlerAgainstElicit(binding, handlerPromise)
        expect(outcome.kind).toBe('sse')
        const sseHandle = outcome.sseHandle!

        const finalizePromise = finalize(sseHandle, callId, handlerPromise)
        // Read the elicit frame to discover the id.
        const reader = sseHandle.response.body!.getReader()
        const decoder = new TextDecoder()
        let buf = ''
        const readFrame = async (): Promise<unknown> => {
            while (!buf.includes('\n\n')) {
                const { value, done } = await reader.read()
                if (done) {
                    throw new Error('closed')
                }
                buf += decoder.decode(value, { stream: true })
            }
            const i = buf.indexOf('\n\n')
            const frame = buf.slice(0, i)
            buf = buf.slice(i + 2)
            const dataLine = frame.split('\n').find((l) => l.startsWith('data: '))
            return JSON.parse(dataLine!.slice('data: '.length))
        }
        const elicitFrame = (await readFrame()) as { id: string }
        await bus.deliver(elicitFrame.id, { action: 'decline' })

        const finalFrame = (await readFrame()) as { id: string; error: { code: number; message: string } }
        expect(finalFrame.id).toBe(callId)
        expect(finalFrame.error.code).toBe(-32603)
        expect(finalFrame.error.message).toBe('user declined')
        await finalizePromise
    })

    it('reads the full SSE body in order: elicit/create then tools/call result, then EOF', async () => {
        // A consolidated end-to-end assertion via readAllFrames, after both
        // writers have flushed and closed. Useful as a regression net.
        const bus = new InMemorySessionResponseBus()
        const binding = new ElicitBinding({
            bus,
            createSseHandle: async () => createSseResponse(),
        })
        const callId = 'call-end-to-end'

        const handlerPromise = (async (): Promise<unknown> => {
            const reply = await binding.invoke({
                message: 'Confirm',
                requestedSchema: { type: 'object', properties: {} },
            })
            return { ok: reply.action === 'accept' }
        })()

        const outcome = await raceHandlerAgainstElicit(binding, handlerPromise)
        const sseHandle = outcome.sseHandle!
        const finalizePromise = finalize(sseHandle, callId, handlerPromise)

        // We need to learn the elicit id before delivering. Peek via a cloned body.
        // Cloning preserves the un-consumed body for the final readAllFrames assertion.
        const clone = sseHandle.response.clone()
        const reader = clone.body!.getReader()
        const decoder = new TextDecoder()
        let buf = ''
        while (!buf.includes('\n\n')) {
            const { value, done } = await reader.read()
            if (done) {
                throw new Error('closed before elicit frame')
            }
            buf += decoder.decode(value, { stream: true })
        }
        const elicitFrame = JSON.parse(
            buf
                .split('\n\n')[0]!
                .split('\n')
                .find((l) => l.startsWith('data: '))!
                .slice('data: '.length)
        ) as { id: string }
        await bus.deliver(elicitFrame.id, { action: 'accept', content: {} })
        await finalizePromise

        const frames = await readAllFrames(sseHandle.response)
        expect(frames).toHaveLength(2)
        expect(frames[0]).toMatchObject({ method: 'elicitation/create' })
        expect(frames[1]).toMatchObject({ id: callId, result: { ok: true } })
    })
})
