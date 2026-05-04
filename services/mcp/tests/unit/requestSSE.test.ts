import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'

vi.mock('@/api/rate-limiter', () => ({
    globalRateLimiter: {
        throttle: vi.fn().mockResolvedValue(undefined),
    },
}))

function createMockStream(chunks: string[]): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder()
    let index = 0
    return new ReadableStream({
        pull(controller) {
            if (index < chunks.length) {
                controller.enqueue(encoder.encode(chunks[index]))
                index++
            } else {
                controller.close()
            }
        },
    })
}

function makeMockFetch(response: Response): typeof fetch {
    return vi.fn().mockResolvedValue(response)
}

describe('ApiClient.requestSSE', () => {
    let client: ApiClient

    beforeEach(() => {
        vi.useFakeTimers()
        client = new ApiClient({
            apiToken: 'test-token',
            baseUrl: 'https://app.posthog.com',
        })
    })

    afterEach(() => {
        vi.clearAllTimers()
        vi.restoreAllMocks()
        vi.useRealTimers()
    })

    it('should parse multiple SSE events and call onEvent for each', async () => {
        const sseBody = [
            'event: summary\ndata: {"session_id": "abc", "summary": {"key": "value"}}\n\n',
            'event: summary\ndata: {"session_id": "def", "summary": {"key": "other"}}\n\n',
            'event: done\ndata: {"completed": ["abc", "def"], "failed": []}\n\n',
        ].join('')

        const mockResponse = new Response(createMockStream([sseBody]), {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' },
        })
        vi.stubGlobal('fetch', makeMockFetch(mockResponse))

        const onEvent = vi.fn()
        const promise = client.requestSSE({
            method: 'GET',
            path: '/api/stream',
            onEvent,
        })
        await vi.runAllTimersAsync()
        await promise

        expect(onEvent).toHaveBeenCalledTimes(3)
        expect(onEvent).toHaveBeenNthCalledWith(1, 'summary', { session_id: 'abc', summary: { key: 'value' } })
        expect(onEvent).toHaveBeenNthCalledWith(2, 'summary', { session_id: 'def', summary: { key: 'other' } })
        expect(onEvent).toHaveBeenNthCalledWith(3, 'done', { completed: ['abc', 'def'], failed: [] })
    })

    it('should skip keepalive comments and only call onEvent for real events', async () => {
        const sseBody = [
            'event: summary\ndata: {"session_id": "abc"}\n\n',
            ': keepalive\n\n',
            ': keepalive\n\n',
            'event: done\ndata: {"completed": ["abc"], "failed": []}\n\n',
        ].join('')

        const mockResponse = new Response(createMockStream([sseBody]), {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' },
        })
        vi.stubGlobal('fetch', makeMockFetch(mockResponse))

        const onEvent = vi.fn()
        const promise = client.requestSSE({
            method: 'GET',
            path: '/api/stream',
            onEvent,
        })
        await vi.runAllTimersAsync()
        await promise

        expect(onEvent).toHaveBeenCalledTimes(2)
        expect(onEvent).toHaveBeenNthCalledWith(1, 'summary', { session_id: 'abc' })
        expect(onEvent).toHaveBeenNthCalledWith(2, 'done', { completed: ['abc'], failed: [] })
    })

    it('should handle chunked delivery by buffering across chunk boundaries', async () => {
        // Split the first event mid-way across two chunks
        const chunks = [
            'event: summary\ndata: {"session_id": "abc"',
            '}\n\nevent: done\ndata: {"completed": ["abc"], "failed": []}\n\n',
        ]

        const mockResponse = new Response(createMockStream(chunks), {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' },
        })
        vi.stubGlobal('fetch', makeMockFetch(mockResponse))

        const onEvent = vi.fn()
        const promise = client.requestSSE({
            method: 'GET',
            path: '/api/stream',
            onEvent,
        })
        await vi.runAllTimersAsync()
        await promise

        expect(onEvent).toHaveBeenCalledTimes(2)
        expect(onEvent).toHaveBeenNthCalledWith(1, 'summary', { session_id: 'abc' })
        expect(onEvent).toHaveBeenNthCalledWith(2, 'done', { completed: ['abc'], failed: [] })
    })

    it('should throw with status code and error text on HTTP error response', async () => {
        const mockResponse = new Response('Unauthorized', {
            status: 401,
            statusText: 'Unauthorized',
        })
        vi.stubGlobal('fetch', makeMockFetch(mockResponse))

        await expect(
            client.requestSSE({
                method: 'GET',
                path: '/api/stream',
                onEvent: vi.fn(),
            })
        ).rejects.toThrow('401')
    })

    it('should throw when response body is missing', async () => {
        const mockResponse = new Response(null, {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' },
        })
        vi.stubGlobal('fetch', makeMockFetch(mockResponse))

        await expect(
            client.requestSSE({
                method: 'GET',
                path: '/api/stream',
                onEvent: vi.fn(),
            })
        ).rejects.toThrow('SSE response has no body')
    })

    it('should throw "SSE read timed out" when no data arrives within the per-read timeout', async () => {
        // Mock the reader so that read() rejects with the per-read timeout error.
        // This directly tests the observable behavior (the error thrown) without
        // relying on fake timers, which would leave dangling timer promises in the
        // cloudflare-workers test environment.
        const mockReader = {
            read: vi.fn().mockRejectedValue(new Error('SSE read timed out — no data received for 30s')),
            releaseLock: vi.fn(),
        }
        const mockBody = {
            getReader: vi.fn().mockReturnValue(mockReader),
        }
        const mockResponse = {
            ok: true,
            body: mockBody,
            text: vi.fn(),
        } as unknown as Response
        vi.stubGlobal('fetch', makeMockFetch(mockResponse))

        await expect(
            client.requestSSE({
                method: 'GET',
                path: '/api/stream',
                onEvent: vi.fn(),
            })
        ).rejects.toThrow('SSE read timed out')
    })

    it('should throw "SSE stream timed out" when overall timeout is exceeded', async () => {
        // Strategy: mock the reader so both read() calls resolve quickly (with keepalives),
        // but advance the fake clock past timeoutMs between calls so the overall timeout
        // check at the top of the loop fires on the second iteration.
        const encoder = new TextEncoder()
        const keepaliveChunk = encoder.encode(': keepalive\n\n')
        const shortTimeoutMs = 500

        // Use a deferred promise for the second read so we can resolve it after
        // advancing the clock, giving the loop a chance to reach the top-of-loop
        // overall timeout check on the next iteration.
        let resolveSecondRead!: (value: ReadableStreamReadResult<Uint8Array>) => void
        const secondReadPromise = new Promise<ReadableStreamReadResult<Uint8Array>>((resolve) => {
            resolveSecondRead = resolve
        })

        const mockReader = {
            read: vi
                .fn()
                .mockResolvedValueOnce({ done: false, value: keepaliveChunk })
                .mockReturnValueOnce(secondReadPromise),
            releaseLock: vi.fn(),
        }
        const mockBody = {
            getReader: vi.fn().mockReturnValue(mockReader),
        }
        const mockResponse = {
            ok: true,
            body: mockBody,
            text: vi.fn(),
        } as unknown as Response
        vi.stubGlobal('fetch', makeMockFetch(mockResponse))

        const promise = client.requestSSE({
            method: 'GET',
            path: '/api/stream',
            onEvent: vi.fn(),
            timeoutMs: shortTimeoutMs,
        })

        // Advance the clock past the overall timeout, then resolve the second read
        // to unblock the loop so it can reach the top-of-loop timeout check.
        await vi.advanceTimersByTimeAsync(shortTimeoutMs + 1)
        resolveSecondRead({ done: false, value: keepaliveChunk })

        await expect(promise).rejects.toThrow(`SSE stream timed out after ${shortTimeoutMs}ms`)
    })

    it('should pass raw string to onEvent when event data is not valid JSON', async () => {
        const sseBody = 'event: status\ndata: plain text not json\n\n'

        const mockResponse = new Response(createMockStream([sseBody]), {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' },
        })
        vi.stubGlobal('fetch', makeMockFetch(mockResponse))

        const onEvent = vi.fn()
        const promise = client.requestSSE({
            method: 'GET',
            path: '/api/stream',
            onEvent,
        })
        await vi.runAllTimersAsync()
        await promise

        expect(onEvent).toHaveBeenCalledTimes(1)
        expect(onEvent).toHaveBeenCalledWith('status', 'plain text not json')
    })

    it('should send Accept: text/event-stream header', async () => {
        const mockFetch = vi.fn().mockResolvedValue(
            new Response(createMockStream([]), {
                status: 200,
                headers: { 'Content-Type': 'text/event-stream' },
            })
        )
        vi.stubGlobal('fetch', mockFetch)

        const promise = client.requestSSE({
            method: 'POST',
            path: '/api/stream',
            body: { session_id: 'abc' },
            onEvent: vi.fn(),
        })
        await vi.runAllTimersAsync()
        await promise

        expect(mockFetch).toHaveBeenCalledOnce()
        const [, options] = mockFetch.mock.calls[0]!
        const headers = options.headers as Record<string, string>
        expect(headers['Accept']).toBe('text/event-stream')
    })

    it('should default event type to "message" when event line is absent', async () => {
        const sseBody = 'data: {"value": 42}\n\n'

        const mockResponse = new Response(createMockStream([sseBody]), {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' },
        })
        vi.stubGlobal('fetch', makeMockFetch(mockResponse))

        const onEvent = vi.fn()
        const promise = client.requestSSE({
            method: 'GET',
            path: '/api/stream',
            onEvent,
        })
        await vi.runAllTimersAsync()
        await promise

        expect(onEvent).toHaveBeenCalledOnce()
        expect(onEvent).toHaveBeenCalledWith('message', { value: 42 })
    })
})
