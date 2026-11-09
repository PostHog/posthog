import { isAppReloadBlocked } from '@/lib/appReload'

import { BUDGETS, BudgetExceededError, resetBudgets } from './budget'
import { apiJson, apiStream, setAuthProvider } from './client'
import { resetServerClock, serverOffsetMs } from './serverClock'
import { createTask, sendTaskRunCommand, startTaskRun } from './tasks'
import { REQUEST_TIMEOUT_MS, RequestTimeoutError, TransportError } from './transport'

jest.mock('expo/fetch', () => ({ fetch: jest.fn() }))

describe('api client send path', () => {
    let fetchMock: jest.Mock

    beforeEach(() => {
        resetBudgets()
        resetServerClock()
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: async () => null,
        })
        fetchMock = jest.fn(async () => ({
            ok: true,
            status: 200,
            headers: { get: (name: string) => (name === 'Date' ? 'Wed, 14 Oct 2026 12:00:30 GMT' : null) },
            text: async () => '{}',
        }))
        globalThis.fetch = fetchMock as unknown as typeof fetch
    })

    afterEach(() => {
        jest.useRealTimers()
        setAuthProvider(null)
    })

    test('identifies mobile creation, continuation and permission answers on every task action', async () => {
        await createTask({
            title: '',
            description: 'Example',
            origin_product: 'posthog_ai',
            initial_permission_mode: 'default',
            pending_user_message: 'Example',
        })
        await startTaskRun('task-1', {
            mode: 'interactive',
            pending_user_message: 'Continue',
            resume_from_run_id: 'run-1',
        })
        await sendTaskRunCommand(
            'task-1',
            'run-1',
            { method: 'user_message', params: { content: 'Continue' } },
            { id: 'message-1' }
        )
        await sendTaskRunCommand(
            'task-1',
            'run-1',
            { method: 'permission_response', params: { requestId: 'question-1', optionId: 'allow' } },
            { id: 'answer-1' }
        )
        expect(fetchMock).toHaveBeenCalledTimes(4)
        for (const [, init] of fetchMock.mock.calls) {
            expect(init).toEqual(
                expect.objectContaining({
                    method: 'POST',
                    headers: expect.objectContaining({ 'X-PostHog-Client-Platform': 'mobile' }),
                })
            )
        }
    })

    test('keeps the server clock offset from the Date header', async () => {
        jest.useFakeTimers({ now: Date.parse('2026-10-14T12:00:00Z') })

        await apiJson('/api/projects/2/insights/1/')

        expect(serverOffsetMs()).toBe(30_000)
    })

    test.each([false, true])('blocks an app reload until a pending request settles, failure=%s', async (failure) => {
        let finish!: (response: unknown) => void
        let fail!: (error: Error) => void
        fetchMock.mockImplementationOnce(
            () =>
                new Promise((resolve, reject) => {
                    finish = resolve
                    fail = reject
                })
        )
        const request = apiJson('/api/projects/2/tasks/task-1/', { method: 'PATCH', json: { archived: true } })
        expect(isAppReloadBlocked()).toBe(true)

        if (failure) {
            fail(new Error('Offline'))
            await expect(request).rejects.toBeInstanceOf(TransportError)
        } else {
            finish({ ok: true, status: 200, text: async () => '{}' })
            await request
        }
        expect(isAppReloadBlocked()).toBe(false)
    })

    test.each(['headers', 'body', 'refresh'])('bounds a hung %s without retrying a write', async (stage) => {
        jest.useFakeTimers()
        let finishRefresh!: (token: string) => void
        if (stage === 'headers') {
            fetchMock.mockImplementation(() => new Promise(() => undefined))
        } else {
            fetchMock.mockResolvedValue({
                ok: stage !== 'refresh',
                status: stage === 'refresh' ? 401 : 200,
                text: () => new Promise(() => undefined),
            })
        }
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: () =>
                new Promise((resolve) => {
                    finishRefresh = resolve
                }),
        })
        const request = apiJson('/api/projects/2/tasks/task-1/', { method: 'PATCH', json: { archived: true } })
        const assertion = expect(request).rejects.toBeInstanceOf(RequestTimeoutError)
        await jest.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS)
        await assertion
        expect(isAppReloadBlocked()).toBe(false)
        expect(fetchMock.mock.calls[0]?.[1].signal.aborted).toBe(true)
        if (stage === 'refresh') {
            finishRefresh('rotated')
            await jest.advanceTimersByTimeAsync(0)
        }
        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(jest.getTimerCount()).toBe(0)
    })

    test.each(['before', 'headers', 'refresh'])('cancels %s without sending a late retry', async (stage) => {
        jest.useFakeTimers()
        let finishRefresh!: (token: string) => void
        let markRefreshStarted!: () => void
        const refreshStarted = new Promise<void>((resolve) => {
            markRefreshStarted = resolve
        })
        const refreshed = new Promise<string>((resolve) => {
            finishRefresh = resolve
        })
        fetchMock.mockImplementation(() =>
            stage === 'refresh' ? Promise.resolve({ status: 401 }) : new Promise(() => undefined)
        )
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: () => {
                markRefreshStarted()
                return refreshed
            },
        })
        const controller = new AbortController()
        if (stage === 'before') {
            controller.abort()
        }
        const request = apiJson('/api/projects/2/tasks/task-1/', { signal: controller.signal })
        const assertion = expect(request).rejects.toMatchObject({ name: 'AbortError' })
        if (stage === 'refresh') {
            await refreshStarted
        }
        controller.abort()
        await assertion
        if (stage === 'refresh') {
            finishRefresh('rotated')
            await refreshed
            await jest.advanceTimersByTimeAsync(0)
        }
        expect(fetchMock).toHaveBeenCalledTimes(stage === 'before' ? 0 : 1)
        expect(isAppReloadBlocked()).toBe(false)
    })

    test.each(['fetch', 'native fetch', 'body', 'serialization'])(
        'classifies %s failures without relabeling serialization errors',
        async (stage) => {
            const failure = new TypeError('Example failure')
            if (stage === 'native fetch') {
                fetchMock.mockRejectedValue(new Error('Example native failure'))
            }
            if (stage === 'fetch') {
                fetchMock.mockRejectedValue(failure)
            }
            if (stage === 'body') {
                fetchMock.mockResolvedValue({
                    ok: true,
                    status: 200,
                    text: async () => {
                        throw failure
                    },
                })
            }
            const json =
                stage === 'serialization'
                    ? {
                          toJSON: () => {
                              throw failure
                          },
                      }
                    : {}
            await expect(apiJson('/api/projects/2/tasks/task-1/', { method: 'POST', json })).rejects.toBeInstanceOf(
                stage === 'serialization' ? TypeError : TransportError
            )
            expect(fetchMock).toHaveBeenCalledTimes(stage === 'serialization' ? 0 : 1)
        }
    )

    test('keeps a live stream open past an ordinary request deadline', async () => {
        jest.useFakeTimers()
        const { fetch: streamFetch } = jest.requireMock('expo/fetch') as { fetch: jest.Mock }
        let open!: (response: unknown) => void
        streamFetch.mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    open = resolve
                })
        )
        const request = apiStream('/api/projects/2/tasks/task-1/runs/run-1/stream/')
        await jest.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS * 2)
        const signal = streamFetch.mock.calls.at(-1)?.[1].signal as AbortSignal | undefined
        expect(signal?.aborted ?? false).toBe(false)
        open({ ok: true, status: 200 })
        await expect(request).resolves.toMatchObject({ status: 200 })
    })

    test('sends nothing once a budget family has used its minute of tokens', async () => {
        const perMinute = BUDGETS.insights[0]?.capacity ?? 0
        for (let index = 0; index < perMinute; index += 1) {
            await apiJson('/api/projects/2/insights/1/')
        }

        await expect(apiJson('/api/projects/2/insights/1/')).rejects.toBeInstanceOf(BudgetExceededError)
        expect(fetchMock).toHaveBeenCalledTimes(perMinute)
        await expect(apiJson('/api/projects/2/dashboards/1/')).resolves.toEqual({})
    })
})
