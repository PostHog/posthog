import { kea, path, resetContext } from 'kea'

import { ApiError } from 'lib/api-error'

import { DisposablesManager, disposablesPlugin } from '~/kea-disposables'

import { submitWithWarmRunRetry } from './warmRunSubmission'

const starting = (token = 'synthetic-retry-token'): ApiError =>
    new ApiError('starting', 503, undefined, { code: 'warm_run_activation_unavailable', retry_token: token })

describe('submitWithWarmRunRetry', () => {
    let logic: ReturnType<typeof kea>
    let disposables: DisposablesManager

    beforeEach(() => {
        jest.useFakeTimers()
        resetContext({ plugins: [disposablesPlugin] })
        logic = kea([path(['test', 'warmRunSubmission'])])
        logic.mount()
        disposables = logic.cache.disposables
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    it('backs off sequentially with the first token, including while the tab is hidden', async () => {
        let complete!: (value: string) => void
        const send = jest
            .fn()
            .mockRejectedValueOnce(starting())
            .mockRejectedValueOnce(starting('another-token'))
            .mockRejectedValueOnce(starting('another-token'))
            .mockReturnValueOnce(new Promise<string>((resolve) => (complete = resolve)))
        const result = submitWithWarmRunRetry(send, disposables)
        await jest.advanceTimersByTimeAsync(249)
        expect(send).toHaveBeenCalledTimes(1)
        await jest.advanceTimersByTimeAsync(1)
        expect(send).toHaveBeenCalledTimes(2)
        jest.spyOn(document, 'hidden', 'get').mockReturnValue(true)
        document.dispatchEvent(new Event('visibilitychange'))
        await jest.advanceTimersByTimeAsync(499)
        expect(send).toHaveBeenCalledTimes(2)
        await jest.advanceTimersByTimeAsync(1)
        expect(send).toHaveBeenCalledTimes(3)
        await jest.advanceTimersByTimeAsync(999)
        expect(send).toHaveBeenCalledTimes(3)
        await jest.advanceTimersByTimeAsync(1)
        expect(send).toHaveBeenCalledTimes(4)
        await jest.advanceTimersByTimeAsync(1000)
        expect(send).toHaveBeenCalledTimes(4)
        expect(send.mock.calls[0][0].headers).toBeUndefined()
        for (const [options] of send.mock.calls.slice(1)) {
            expect(options.headers).toEqual({ 'X-PostHog-Warm-Retry': 'synthetic-retry-token' })
            expect(options.signal).toBe(send.mock.calls[0][0].signal)
        }
        complete('accepted')
        await expect(result).resolves.toBe('accepted')
        expect(disposables.registry.size).toBe(0)
        expect(jest.getTimerCount()).toBe(0)
    })

    test.each([
        new Error('network failure'),
        new DOMException('request timed out', 'TimeoutError'),
        new ApiError('unavailable', 503),
        new ApiError('unavailable', 500, undefined, { code: 'warm_run_activation_unavailable', retry_token: 'token' }),
        new ApiError('unavailable', 503, undefined, { code: 'another_error', retry_token: 'token' }),
        starting(''),
        starting(' '),
        new ApiError('starting', 503, undefined, { code: 'warm_run_activation_unavailable', retry_token: 1 }),
    ])('stops without retrying an unconfirmed failure: %s', async (error) => {
        const send = jest.fn().mockRejectedValueOnce(starting()).mockRejectedValueOnce(error)
        const result = submitWithWarmRunRetry(send, disposables)
        const rejected = result.catch((error) => error)
        await jest.advanceTimersByTimeAsync(20_000)
        await expect(rejected).resolves.toBe(error)
        expect(send).toHaveBeenCalledTimes(2)
        expect(disposables.registry.size).toBe(0)
    })

    test.each(['backoff', 'request'])(
        'expires at 20 seconds during %s, counting the initial request',
        async (phase) => {
            const error = starting()
            let rejectInitial!: (error: Error) => void
            let complete!: (value: string) => void
            const send = jest.fn().mockReturnValueOnce(new Promise((_, reject) => (rejectInitial = reject)))
            if (phase === 'backoff') {
                send.mockRejectedValue(error)
            } else {
                send.mockReturnValue(new Promise<string>((resolve) => (complete = resolve)))
            }
            const result = submitWithWarmRunRetry(send, disposables)
            const rejected = result.catch((error) => error)
            await jest.advanceTimersByTimeAsync(10_000)
            rejectInitial(error)
            await jest.advanceTimersByTimeAsync(9_999)
            expect(send.mock.calls[0][0].signal.aborted).toBe(false)
            const attempts = send.mock.calls.length
            await jest.advanceTimersByTimeAsync(1)
            await expect(rejected).resolves.toBe(error)
            expect(send.mock.calls[0][0].signal.aborted).toBe(true)
            complete?.('late acceptance')
            await jest.advanceTimersByTimeAsync(20_000)
            expect(send).toHaveBeenCalledTimes(attempts)
            expect(disposables.registry.size).toBe(0)
            expect(jest.getTimerCount()).toBe(0)
        }
    )

    test.each(['initial request', 'backoff', 'retry request'])('cancels on unmount during %s', async (phase) => {
        let complete!: (value: string) => void
        const pending = new Promise<string>((resolve) => (complete = resolve))
        const send = jest.fn().mockReturnValue(pending)
        if (phase !== 'initial request') {
            send.mockRejectedValueOnce(starting())
        }
        const result = submitWithWarmRunRetry(send, disposables)
        const rejected = result.catch((error) => error)
        await jest.advanceTimersByTimeAsync(phase === 'retry request' ? 250 : 0)
        logic.unmount()
        await expect(rejected).resolves.toMatchObject({ name: 'AbortError' })
        const attempts = send.mock.calls.length
        logic.mount()
        complete('obsolete acceptance')
        await jest.advanceTimersByTimeAsync(20_000)
        expect(send).toHaveBeenCalledTimes(attempts)
        expect(send.mock.calls[0][0].signal.aborted).toBe(true)
        expect(disposables.registry.size).toBe(0)
        await expect(submitWithWarmRunRetry(send, disposables)).rejects.toMatchObject({ name: 'AbortError' })
        expect(send).toHaveBeenCalledTimes(attempts)
    })

    it('does not impose the warm deadline on an ordinary cold submission', async () => {
        let complete!: (value: string) => void
        const send = jest.fn().mockReturnValue(new Promise<string>((resolve) => (complete = resolve)))
        const result = submitWithWarmRunRetry(send, disposables)
        await jest.advanceTimersByTimeAsync(30_000)
        expect(send.mock.calls[0][0].signal.aborted).toBe(false)
        complete('cold acceptance')
        await expect(result).resolves.toBe('cold acceptance')
        expect(send).toHaveBeenCalledTimes(1)
    })
})
