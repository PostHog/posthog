import { setSessionTokens } from '@/auth/tokens'

import { BudgetExceededError, resetBudgets, trySpend } from './budget'
import { apiJson, setAuthProvider } from './client'
import { withReplayBudget } from './replayBudget'

describe('replay request budget waiting', () => {
    beforeEach(() => {
        jest.useFakeTimers({ now: 0 })
        resetBudgets()
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: async () => null,
        })
        globalThis.fetch = jest.fn(async () => ({
            ok: true,
            status: 200,
            text: async () => '{}',
        })) as unknown as typeof fetch
    })

    afterEach(() => {
        jest.useRealTimers()
        setAuthProvider(null)
    })

    test.each([
        ['minute', 1, 1000],
        ['hour', 6, 12000],
    ])('queues competing requests until the %s bucket refills', async (_window, batches, delay) => {
        for (let batch = 0; batch < batches; batch++) {
            if (batch > 0) await jest.advanceTimersByTimeAsync(60_000)
            while (trySpend('replay')) {}
        }
        const controller = new AbortController()
        const states: string[] = []
        const requests = Array.from({ length: 6 }, () =>
            withReplayBudget(
                () => apiJson('/api/projects/2/session_recordings/example/snapshots/', { budgetFamily: 'replay' }),
                controller.signal,
                (state) => states.push(state)
            )
        )
        await jest.advanceTimersByTimeAsync(delay - 1)
        expect(fetch).not.toHaveBeenCalled()
        expect(states.at(-1)).toBe('queued')
        await jest.advanceTimersByTimeAsync(1)
        expect(fetch).toHaveBeenCalledTimes(1)
        await jest.advanceTimersByTimeAsync(delay * 5)
        await expect(Promise.all(requests)).resolves.toEqual(Array.from({ length: 6 }, () => ({})))
        expect(fetch).toHaveBeenCalledTimes(6)
        expect(jest.getTimerCount()).toBe(0)
    })

    test.each(['abort', 'session'])('does not dispatch a queued request after %s changes', async (change) => {
        while (trySpend('replay')) {}
        const controller = new AbortController()
        const request = withReplayBudget(
            () => apiJson('/api/projects/2/session_recordings/example/snapshots/', { budgetFamily: 'replay' }),
            controller.signal
        )
        const assertion = expect(request).rejects.toMatchObject({ name: 'AbortError' })
        await jest.advanceTimersByTimeAsync(0)
        if (change === 'abort') controller.abort()
        else setSessionTokens(null)
        await jest.advanceTimersByTimeAsync(1000)
        await assertion
        expect(fetch).not.toHaveBeenCalled()
        expect(jest.getTimerCount()).toBe(0)
    })

    test.each([new BudgetExceededError('query'), new Error('Example request failure')])(
        'does not retry a failure outside the replay budget: %s',
        async (failure) => {
            const request = withReplayBudget(async () => {
                throw failure
            }, new AbortController().signal)
            await expect(request).rejects.toBe(failure)
            expect(jest.getTimerCount()).toBe(0)
        }
    )
})
