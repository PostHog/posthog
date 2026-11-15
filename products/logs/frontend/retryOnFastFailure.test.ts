import { FAST_FAILURE_MS, retryOnFastFailure } from './retryOnFastFailure'

function statusError(status: number): Error & { status: number } {
    return Object.assign(new Error(`status ${status}`), { status })
}

describe('retryOnFastFailure', () => {
    let now: number

    beforeEach(() => {
        now = 0
        jest.spyOn(performance, 'now').mockImplementation(() => now)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('retries a fast failure once and returns the retry result', async () => {
        const fn = jest.fn().mockRejectedValueOnce(statusError(503)).mockResolvedValueOnce('ok')

        await expect(retryOnFastFailure(fn, { retryDelayMs: 0 })).resolves.toBe('ok')
        expect(fn).toHaveBeenCalledTimes(2)
    })

    it('throws when the retry also fails', async () => {
        const fn = jest.fn().mockRejectedValueOnce(new Error('first')).mockRejectedValueOnce(new Error('second'))

        await expect(retryOnFastFailure(fn, { retryDelayMs: 0 })).rejects.toThrow('second')
        expect(fn).toHaveBeenCalledTimes(2)
    })

    it('does not retry a failure that took longer than the fast-failure window', async () => {
        const fn = jest.fn().mockImplementationOnce(async () => {
            now = FAST_FAILURE_MS + 1
            throw statusError(504)
        })

        await expect(retryOnFastFailure(fn, { retryDelayMs: 0 })).rejects.toThrow('status 504')
        expect(fn).toHaveBeenCalledTimes(1)
    })

    it.each([400, 403, 404, 429])('does not retry a %s', async (status) => {
        const fn = jest.fn().mockRejectedValueOnce(statusError(status))

        await expect(retryOnFastFailure(fn, { retryDelayMs: 0 })).rejects.toThrow(`status ${status}`)
        expect(fn).toHaveBeenCalledTimes(1)
    })

    it('does not retry once the signal is aborted', async () => {
        const controller = new AbortController()
        const fn = jest.fn().mockImplementationOnce(async () => {
            controller.abort()
            throw new Error('new query started')
        })

        await expect(retryOnFastFailure(fn, { signal: controller.signal, retryDelayMs: 0 })).rejects.toThrow()
        expect(fn).toHaveBeenCalledTimes(1)
    })
})
