import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { VisualReviewApiError, VisualReviewClient } from './client.js'

const mockFetch = vi.fn()
global.fetch = mockFetch

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
    return {
        ok: status >= 200 && status < 300,
        status,
        headers: new Headers(headers),
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
    } as unknown as Response
}

describe('VisualReviewClient retry logic', () => {
    let client: VisualReviewClient

    beforeEach(() => {
        mockFetch.mockReset()
        vi.useFakeTimers()
        client = new VisualReviewClient({
            apiUrl: 'https://vr.example.com',
            teamId: '1',
            token: 'test-token',
        })
    })

    afterEach(() => {
        vi.useRealTimers()
        vi.restoreAllMocks()
    })

    it('returns parsed JSON on a successful response', async () => {
        mockFetch.mockResolvedValueOnce(jsonResponse({ id: '123' }))

        const result = await client.getRun('run-1')
        expect(result).toEqual({ id: '123' })
        expect(mockFetch).toHaveBeenCalledTimes(1)
    })

    it('throws immediately on 4xx errors without retrying', async () => {
        mockFetch.mockResolvedValueOnce(jsonResponse({ error: 'unauthorized' }, 401))

        await expect(client.getRun('run-1')).rejects.toThrow(VisualReviewApiError)
        expect(mockFetch).toHaveBeenCalledTimes(1)
    })

    it('retries on 5xx and succeeds on second attempt', async () => {
        mockFetch
            .mockResolvedValueOnce(jsonResponse({ error: 'internal' }, 500))
            .mockResolvedValueOnce(jsonResponse({ id: 'ok' }))

        const promise = client.getRun('run-1')
        // Advance past the 1s backoff delay
        await vi.advanceTimersByTimeAsync(1000)

        const result = await promise
        expect(result).toEqual({ id: 'ok' })
        expect(mockFetch).toHaveBeenCalledTimes(2)
    })

    it('exhausts all 3 retries on persistent 5xx then throws the last error', async () => {
        mockFetch.mockResolvedValue(jsonResponse({ error: 'down' }, 502))

        const promise = client.getRun('run-1').catch((e) => e)
        // 3 retries with delays: 1s, 2s, 4s
        await vi.advanceTimersByTimeAsync(1000)
        await vi.advanceTimersByTimeAsync(2000)
        await vi.advanceTimersByTimeAsync(4000)

        const err = await promise
        expect(err).toBeInstanceOf(VisualReviewApiError)
        expect(err.status).toBe(502)
        // 1 initial + 3 retries = 4 total calls
        expect(mockFetch).toHaveBeenCalledTimes(4)
    })

    it('uses Retry-After header delay for 429 responses', async () => {
        mockFetch
            .mockResolvedValueOnce(jsonResponse({ error: 'rate limited' }, 429, { 'Retry-After': '5' }))
            .mockResolvedValueOnce(jsonResponse({ id: 'ok' }))

        const promise = client.getRun('run-1')
        // Should wait 5s (from Retry-After) not 1s (from exponential backoff)
        await vi.advanceTimersByTimeAsync(5000)

        const result = await promise
        expect(result).toEqual({ id: 'ok' })
        expect(mockFetch).toHaveBeenCalledTimes(2)
    })

    it('uses exponential backoff delays (1s, 2s, 4s) for 5xx errors', async () => {
        const timeouts: number[] = []
        const originalSetTimeout = globalThis.setTimeout
        vi.spyOn(globalThis, 'setTimeout').mockImplementation((fn: TimerHandler, ms?: number) => {
            if (ms && ms >= 1000) {
                timeouts.push(ms)
            }
            return originalSetTimeout(fn as () => void, ms)
        })

        mockFetch
            .mockResolvedValueOnce(jsonResponse({ error: 'err' }, 503))
            .mockResolvedValueOnce(jsonResponse({ error: 'err' }, 503))
            .mockResolvedValueOnce(jsonResponse({ error: 'err' }, 503))
            .mockResolvedValueOnce(jsonResponse({ id: 'ok' }))

        const promise = client.getRun('run-1')
        await vi.advanceTimersByTimeAsync(1000)
        await vi.advanceTimersByTimeAsync(2000)
        await vi.advanceTimersByTimeAsync(4000)

        await promise
        expect(timeouts).toEqual([1000, 2000, 4000])
    })
})
