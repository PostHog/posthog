import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    ClaudeRuntimeAdapterEnumApi,
    InitialPermissionModeEnumApi,
    WarmTaskRequestOriginProductEnumApi,
    type WarmTaskRequestApi,
} from 'products/tasks/frontend/generated/api.schemas'

import { taskWarmLogic } from './taskWarmLogic'

const WARM_REQUEST: WarmTaskRequestApi = {
    repository: 'posthog/posthog',
    github_integration: 1,
    branch: 'master',
    runtime_adapter: ClaudeRuntimeAdapterEnumApi.Claude,
    model: 'claude-sonnet-5',
    initial_permission_mode: InitialPermissionModeEnumApi.Auto,
    origin_product: WarmTaskRequestOriginProductEnumApi.PosthogAi,
}

describe('taskWarmLogic', () => {
    let logic: ReturnType<typeof taskWarmLogic.build>
    let warmCalls: number
    let cancelledRuns: string[]
    let resolveWarm: ((value: unknown) => void) | null

    beforeEach(() => {
        warmCalls = 0
        cancelledRuns = []
        resolveWarm = null
        useMocks({
            post: {
                '/api/projects/:team/tasks/warm/': async () => {
                    warmCalls += 1
                    return [200, { task_id: `warm-task-${warmCalls}`, run_id: `warm-run-${warmCalls}` }]
                },
                '/api/projects/:team/tasks/:taskId/runs/:runId/command/': async ({ params }) => {
                    cancelledRuns.push(params.runId as string)
                    return [200, {}]
                },
            },
        })
        initKeaTests()
        logic = taskWarmLogic({ panelId: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    it('warms after the debounce and holds the lease', async () => {
        jest.useFakeTimers()
        logic.actions.noteDraft(true, WARM_REQUEST)
        jest.advanceTimersByTime(300)
        jest.useRealTimers()

        await expectLogic(logic).toFinishAllListeners()
        expect(warmCalls).toBe(1)
        expect(logic.values.warmLease).toMatchObject({ taskId: 'warm-task-1', runId: 'warm-run-1' })
    })

    it('consuming a warm on submit clears the lease without cancelling the run', async () => {
        jest.useFakeTimers()
        logic.actions.noteDraft(true, WARM_REQUEST)
        jest.advanceTimersByTime(300)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.consumeWarm()
        await expectLogic(logic).toFinishAllListeners()

        // The submit activates this very Run — cancelling it would kill the run out from under the message.
        expect(logic.values.warmLease).toBeNull()
        expect(cancelledRuns).toEqual([])
    })

    it('releases the warm when the draft is abandoned', async () => {
        jest.useFakeTimers()
        logic.actions.noteDraft(true, WARM_REQUEST)
        jest.advanceTimersByTime(300)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.releaseWarm()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.warmLease).toBeNull()
        expect(cancelledRuns).toEqual(['warm-run-1'])
    })

    it('honors a release that raced an in-flight warm request', async () => {
        // Abandoning while the POST is still open hits the "nothing to release yet" branch. Without the
        // deferred intent the sandbox that lands a moment later is orphaned until the server reaps it.
        useMocks({
            post: {
                '/api/projects/:team/tasks/warm/': async () => {
                    await new Promise((resolve) => {
                        resolveWarm = resolve
                    })
                    return [200, { task_id: 'warm-task-1', run_id: 'warm-run-1' }]
                },
                '/api/projects/:team/tasks/:taskId/runs/:runId/command/': async ({ params }) => {
                    cancelledRuns.push(params.runId as string)
                    return [200, {}]
                },
            },
        })

        logic.actions.prewarm(WARM_REQUEST)
        await expectLogic(logic).toMount()
        logic.actions.releaseWarm()

        resolveWarm?.(undefined)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.warmLease).toBeNull()
        expect(cancelledRuns).toEqual(['warm-run-1'])
    })

    it('releases and re-warms when the selection changes under an existing warm', async () => {
        jest.useFakeTimers()
        logic.actions.noteDraft(true, WARM_REQUEST)
        jest.advanceTimersByTime(300)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()

        jest.useFakeTimers()
        logic.actions.noteDraft(true, { ...WARM_REQUEST, branch: 'feature' })
        jest.advanceTimersByTime(300)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()

        // The first sandbox is checked out on the wrong branch, so it can never serve this submit.
        expect(cancelledRuns).toEqual(['warm-run-1'])
        expect(warmCalls).toBe(2)
        expect(logic.values.warmLease).toMatchObject({ runId: 'warm-run-2' })
    })

    it('does not re-warm while the selection is unchanged', async () => {
        jest.useFakeTimers()
        logic.actions.noteDraft(true, WARM_REQUEST)
        jest.advanceTimersByTime(300)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()

        jest.useFakeTimers()
        logic.actions.noteDraft(true, { ...WARM_REQUEST })
        jest.advanceTimersByTime(300)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()

        expect(warmCalls).toBe(1)
    })
})
