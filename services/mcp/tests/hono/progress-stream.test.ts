import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { progressStreamResponse, type ToolCallHooks } from '@/hono/progress-stream'

describe('progressStreamResponse', () => {
    beforeEach(() => {
        vi.useFakeTimers()
    })

    afterEach(() => {
        vi.useRealTimers()
    })

    function start(): {
        response: Response
        reader: ReadableStreamDefaultReader<Uint8Array>
        hooks: Required<ToolCallHooks>
        finish: (response: unknown) => void
    } {
        let hooks: Required<ToolCallHooks> | undefined
        let finish: (response: unknown) => void = () => {}
        const response = progressStreamResponse({
            requestId: 1,
            progressToken: 'tok',
            headers: {},
            heartbeatIntervalMs: 1000,
            run: (h) => {
                hooks = h
                return new Promise((resolve) => {
                    finish = resolve
                })
            },
        })
        return { response, reader: response.body!.getReader(), hooks: hooks!, finish }
    }

    async function readEvent(reader: ReadableStreamDefaultReader<Uint8Array>): Promise<unknown> {
        const { value } = await reader.read()
        return JSON.parse(new TextDecoder().decode(value).replace(/^event: message\ndata: /, ''))
    }

    it('re-sends the last message after a quiet interval and stops when the call ends', async () => {
        const { reader, hooks, finish } = start()

        vi.advanceTimersByTime(1000)
        expect(await readEvent(reader)).toMatchObject({ params: { progress: 1, message: 'Working' } })

        hooks.reportProgress('Querying')
        expect(await readEvent(reader)).toMatchObject({ params: { progress: 2, message: 'Querying' } })
        vi.advanceTimersByTime(999)
        hooks.reportProgress('Summarizing')
        expect(await readEvent(reader)).toMatchObject({ params: { progress: 3, message: 'Summarizing' } })
        vi.advanceTimersByTime(1000)
        expect(await readEvent(reader)).toMatchObject({ params: { progress: 4, message: 'Summarizing' } })

        finish({ jsonrpc: '2.0', id: 1, result: {} })
        expect(await readEvent(reader)).toEqual({ jsonrpc: '2.0', id: 1, result: {} })
        expect(await reader.read()).toEqual({ done: true, value: undefined })
        expect(vi.getTimerCount()).toBe(0)
    })

    it('aborts the signal and stops the heartbeat when the client cancels the stream', async () => {
        const { reader, hooks } = start()

        await reader.cancel()

        expect(hooks.signal.aborted).toBe(true)
        expect(vi.getTimerCount()).toBe(0)
    })
})
