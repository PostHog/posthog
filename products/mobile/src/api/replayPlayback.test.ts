import { isAppReloadBlocked } from '@/lib/appReload'

import { resetBudgets } from './budget'
import { ApiError, setAuthProvider } from './client'
import { fetchReplayBlock, MAX_PLAYER_BYTES, ReplayByteBudget } from './replayPlayback'
import { REQUEST_TIMEOUT_MS, RequestTimeoutError, TransportError } from './transport'

jest.mock('expo/fetch', () => ({ fetch: jest.fn() }))

function streamedResponse(
    chunks: Uint8Array[],
    complete = true
): {
    response: Response
    reader: { read: jest.Mock; cancel: jest.Mock; releaseLock: jest.Mock }
} {
    let finish: ((result: { done: true; value: undefined }) => void) | undefined
    const reader = {
        read: jest.fn(async () => {
            const value = chunks.shift()
            if (value) return { value, done: false }
            if (complete) return { value: undefined, done: true }
            return new Promise<{ done: true; value: undefined }>((resolve) => {
                finish = resolve
            })
        }),
        cancel: jest.fn(async () => finish?.({ done: true, value: undefined })),
        releaseLock: jest.fn(),
    }
    return {
        response: {
            ok: true,
            status: 200,
            body: { getReader: () => reader },
            text: () => {
                throw new Error('Replay bodies must be streamed')
            },
        } as unknown as Response,
        reader,
    }
}

describe('bounded replay block transport', () => {
    const streamFetch = jest.requireMock('expo/fetch').fetch as jest.Mock

    beforeEach(() => {
        jest.useFakeTimers()
        resetBudgets()
        streamFetch.mockReset()
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: async () => null,
        })
    })

    afterEach(() => {
        jest.useRealTimers()
        setAuthProvider(null)
    })

    test('decodes split UTF8 while preserving authentication and snapshot query parameters', async () => {
        const bytes = new TextEncoder().encode('Größe\n')
        const { response, reader } = streamedResponse([bytes.slice(0, 3), bytes.slice(3)])
        streamFetch.mockResolvedValue(response)
        await expect(
            fetchReplayBlock('example/session', { source: 'blob_v2', blob_key: '17' }, new AbortController().signal, {
                budget: new ReplayByteBudget(),
            })
        ).resolves.toBe('Größe\n')
        expect(streamFetch).toHaveBeenCalledWith(
            'https://app.example.com/api/projects/2/session_recordings/example%2Fsession/snapshots/?source=blob_v2&start_blob_key=17&end_blob_key=17&decompress=true',
            expect.objectContaining({
                headers: expect.objectContaining({ Authorization: 'Bearer token', Accept: 'application/json' }),
            })
        )
        expect(reader.cancel).not.toHaveBeenCalled()
        expect(reader.releaseLock).toHaveBeenCalled()
        expect(isAppReloadBlocked()).toBe(false)
        expect(jest.getTimerCount()).toBe(0)
    })

    test.each(['encoded', 'decoded'] as const)(
        'enforces the shared %s limit across concurrent incomplete blocks',
        async (limit) => {
            const budget = new ReplayByteBudget()
            if (limit === 'encoded') budget.claimEncoded(MAX_PLAYER_BYTES - 3)
            else budget.claimDecoded(MAX_PLAYER_BYTES - 6)
            const streams = [
                streamedResponse([new Uint8Array([65, 66])], false),
                streamedResponse([new Uint8Array([67, 68])], false),
            ]
            for (const { response } of streams) streamFetch.mockResolvedValueOnce(response)
            const controller = new AbortController()
            const requests = streams.map((_stream, index) =>
                fetchReplayBlock('example', { source: 'blob_v2', blob_key: String(index) }, controller.signal, {
                    budget,
                })
            )
            const result = Promise.all(requests).catch((error: unknown) => {
                controller.abort()
                throw error
            })
            await expect(result).rejects.toThrow('This recording is too large to play on this device.')
            await Promise.allSettled(requests)
            for (const { reader } of streams) {
                expect(reader.read.mock.calls.length).toBeLessThanOrEqual(2)
                expect(reader.cancel).toHaveBeenCalled()
                expect(reader.releaseLock).toHaveBeenCalled()
            }
            expect(isAppReloadBlocked()).toBe(false)
            expect(jest.getTimerCount()).toBe(0)
        }
    )

    test.each(['timeout', 'abort', 'transport'] as const)(
        'cancels an unfinished stream on %s and releases reload blocking',
        async (failure) => {
            const { response, reader } = streamedResponse([], false)
            streamFetch.mockResolvedValue(response)
            if (failure === 'transport') reader.read.mockRejectedValue(new Error('Offline'))
            const controller = new AbortController()
            const request = fetchReplayBlock('example', { source: 'blob_v2', blob_key: '0' }, controller.signal, {
                budget: new ReplayByteBudget(),
            })
            const assertion =
                failure === 'abort'
                    ? expect(request).rejects.toMatchObject({ name: 'AbortError' })
                    : expect(request).rejects.toBeInstanceOf(
                          failure === 'timeout' ? RequestTimeoutError : TransportError
                      )
            expect(isAppReloadBlocked()).toBe(true)
            await jest.advanceTimersByTimeAsync(0)
            if (failure === 'timeout') await jest.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS)
            if (failure === 'abort') controller.abort()
            await assertion
            expect(reader.cancel).toHaveBeenCalled()
            expect(reader.releaseLock).toHaveBeenCalled()
            expect(isAppReloadBlocked()).toBe(false)
            expect(jest.getTimerCount()).toBe(0)
        }
    )

    test('rejects HTTP failures without buffering the error body', async () => {
        const cancel = jest.fn(async () => undefined)
        const text = jest.fn(() => new Promise(() => undefined))
        streamFetch.mockResolvedValue({ ok: false, status: 503, body: { cancel }, text })
        await expect(
            fetchReplayBlock('example', { source: 'blob_v2', blob_key: '0' }, new AbortController().signal, {
                budget: new ReplayByteBudget(),
            })
        ).rejects.toBeInstanceOf(ApiError)
        expect(text).not.toHaveBeenCalled()
        expect(cancel).toHaveBeenCalled()
        expect(isAppReloadBlocked()).toBe(false)
    })
})
