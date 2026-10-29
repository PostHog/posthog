import { isAppReloadBlocked } from '@/lib/appReload'

import { BUDGETS, BudgetExceededError, resetBudgets } from './budget'
import { apiJson, setAuthProvider } from './client'
import { resetServerClock, serverOffsetMs } from './serverClock'
import { createTask, sendTaskRunCommand, startTaskRun } from './tasks'

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
            await expect(request).rejects.toThrow('Offline')
        } else {
            finish({ ok: true, status: 200, text: async () => '{}' })
            await request
        }
        expect(isAppReloadBlocked()).toBe(false)
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
