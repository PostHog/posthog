import { act, cleanup, renderHook } from '@testing-library/react-native'

import { RECONNECT_CHECK_TIMEOUT_MS, RECONNECT_NOTICE_DELAY_MS, useDelayedReconnecting } from './useDelayedReconnecting'

describe('useDelayedReconnecting', () => {
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    test.each(['failed', 'timeout'] as const)('verifies once before showing a warning after %s', async (outcome) => {
        let reject!: (error: Error) => void
        let signal!: AbortSignal
        const check = jest.fn((nextSignal: AbortSignal) => {
            signal = nextSignal
            return new Promise<void>((_resolve, rejectPromise) => {
                reject = rejectPromise
            })
        })
        const { result, rerender } = renderHook(() => useDelayedReconnecting(true, 'project', check))
        await act(async () => jest.advanceTimersByTimeAsync(RECONNECT_NOTICE_DELAY_MS))
        expect(check).toHaveBeenCalledTimes(1)
        expect(result.current).toBe(false)
        await act(async () => {
            if (outcome === 'failed') reject(new Error('offline'))
            else await jest.advanceTimersByTimeAsync(RECONNECT_CHECK_TIMEOUT_MS)
        })
        expect(result.current).toBe(true)
        expect(signal.aborted).toBe(true)
        rerender({})
        await act(async () => jest.advanceTimersByTimeAsync(RECONNECT_NOTICE_DELAY_MS))
        expect(check).toHaveBeenCalledTimes(1)
    })

    test.each(['recovery', 'scope change', 'unmount'] as const)(
        'cancels pending verification on %s',
        async (change) => {
            let finish!: () => void
            let signal!: AbortSignal
            const check = jest.fn((nextSignal: AbortSignal) => {
                signal = nextSignal
                return new Promise<void>((resolve) => {
                    finish = resolve
                })
            })
            const { result, rerender, unmount } = renderHook<boolean, { failing: boolean; scope: string }>(
                ({ failing, scope }) => useDelayedReconnecting(failing, scope, check),
                { initialProps: { failing: true, scope: 'first' } }
            )
            await act(async () => jest.advanceTimersByTimeAsync(RECONNECT_NOTICE_DELAY_MS))
            expect(result.current).toBe(false)
            if (change === 'unmount') unmount()
            else rerender({ failing: change !== 'recovery', scope: change === 'scope change' ? 'second' : 'first' })
            expect(signal.aborted).toBe(true)
            await act(async () => {
                finish()
                await jest.advanceTimersByTimeAsync(RECONNECT_CHECK_TIMEOUT_MS)
            })
            expect(result.current).toBe(false)
            expect(check).toHaveBeenCalledTimes(1)
        }
    )
})
