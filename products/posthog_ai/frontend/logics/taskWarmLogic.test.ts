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
                '/api/projects/:team/tasks/:taskId/runs/:runId/cancel/': async ({ params }) => {
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
        // A test may unmount the logic itself (to exercise beforeUnmount); guard against a double unmount.
        if (logic.isMounted()) {
            logic.unmount()
        }
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

    it('warms again for the next draft after a submit consumed the previous warm', async () => {
        jest.useFakeTimers()
        logic.actions.noteDraft(true, WARM_REQUEST)
        jest.advanceTimersByTime(300)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()
        expect(warmCalls).toBe(1)

        logic.actions.consumeWarm()
        await expectLogic(logic).toFinishAllListeners()

        jest.useFakeTimers()
        logic.actions.noteDraft(true, WARM_REQUEST)
        jest.advanceTimersByTime(300)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()

        expect(warmCalls).toBe(2)
        expect(logic.values.warmLease).toMatchObject({ taskId: 'warm-task-2', runId: 'warm-run-2' })
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
                '/api/projects/:team/tasks/:taskId/runs/:runId/cancel/': async ({ params }) => {
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

    it('warms a fresh task through the create endpoint even when mounted under the new-task route', async () => {
        // The scene passes the `/tasks/:taskId` route param down, so this logic can be keyed on the `new`
        // sentinel. Routing on that prop sent the fresh-task body to `tasks/new/warm/`, which the server
        // rejects for a missing `resume_from_run_id` — the composer then never warmed at all.
        let resumeCalls = 0
        useMocks({
            post: {
                '/api/projects/:team/tasks/warm/': async () => {
                    warmCalls += 1
                    return [200, { task_id: 'warm-task-1', run_id: 'warm-run-1' }]
                },
                '/api/projects/:team/tasks/:taskId/warm/': async () => {
                    resumeCalls += 1
                    return [400, { attr: 'resume_from_run_id', code: 'required' }]
                },
            },
        })
        logic.unmount()
        logic = taskWarmLogic({ panelId: 'new-route', taskId: 'new' })
        logic.mount()

        jest.useFakeTimers()
        logic.actions.noteDraft(true, WARM_REQUEST)
        jest.advanceTimersByTime(300)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()

        expect(resumeCalls).toBe(0)
        expect(warmCalls).toBe(1)
        expect(logic.values.warmLease).toMatchObject({ runId: 'warm-run-1' })
    })

    it('asks once per selection when the server answers that it did not warm', async () => {
        // An empty body ("flag off", "pool full", "integration didn't resolve") installs no lease, so
        // the lease check can't stop the next typing pause from asking again. Before the cooldown that
        // was one POST every couple of hundred milliseconds for the length of the draft.
        useMocks({
            post: {
                '/api/projects/:team/tasks/warm/': async () => {
                    warmCalls += 1
                    return [200, {}]
                },
            },
        })

        jest.useFakeTimers()
        logic.actions.noteDraft(true, WARM_REQUEST)
        jest.advanceTimersByTime(300)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()
        expect(warmCalls).toBe(1)
        expect(logic.values.warmLease).toBeNull()

        jest.useFakeTimers()
        logic.actions.noteDraft(true, WARM_REQUEST)
        logic.actions.noteDraft(true, WARM_REQUEST)
        jest.advanceTimersByTime(300)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()
        expect(warmCalls).toBe(1)

        // Past the cooldown the composer tries once more, in case the answer has changed.
        jest.useFakeTimers()
        jest.setSystemTime(Date.now() + 6 * 60 * 1000)
        logic.actions.noteDraft(true, WARM_REQUEST)
        jest.advanceTimersByTime(300)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()
        expect(warmCalls).toBe(2)
    })

    it('re-warms for a selection changed while the first warm was still in flight', async () => {
        // Hold the first warm POST open so a model change collides with it. Without queuing the newer
        // selection, the completing POST leaves the lease on the stale model and never warms the new
        // one, so the submit silently takes the cold path and the first sandbox idles until the reaper.
        let resolveFirst: () => void = () => {}
        useMocks({
            post: {
                '/api/projects/:team/tasks/warm/': async () => {
                    warmCalls += 1
                    const n = warmCalls
                    if (n === 1) {
                        await new Promise<void>((resolve) => {
                            resolveFirst = resolve
                        })
                    }
                    return [200, { task_id: `warm-task-${n}`, run_id: `warm-run-${n}` }]
                },
                '/api/projects/:team/tasks/:taskId/runs/:runId/cancel/': async ({ params }) => {
                    cancelledRuns.push(params.runId as string)
                    return [200, {}]
                },
            },
        })

        logic.actions.prewarm(WARM_REQUEST)
        await expectLogic(logic).toMount()
        // A different model arrives before the first warm resolves.
        logic.actions.prewarm({ ...WARM_REQUEST, model: 'claude-opus-4-8' })

        resolveFirst()
        await expectLogic(logic).toFinishAllListeners()

        // The stale first sandbox is released and the latest selection is the one left warm.
        expect(warmCalls).toBe(2)
        expect(cancelledRuns).toEqual(['warm-run-1'])
        expect(logic.values.warmLease).toMatchObject({ runId: 'warm-run-2' })
    })

    it('keeps a warm the user re-engaged after a release raced the in-flight POST', async () => {
        // Release fires while the POST is open (no lease yet), then the user types the same selection
        // again before it resolves. Re-engaging must clear the deferred release so the landing sandbox
        // is kept, not cancelled the moment it appears.
        let resolveHeldWarm: () => void = () => {}
        useMocks({
            post: {
                '/api/projects/:team/tasks/warm/': async () => {
                    await new Promise<void>((resolve) => {
                        resolveHeldWarm = resolve
                    })
                    return [200, { task_id: 'warm-task-1', run_id: 'warm-run-1' }]
                },
                '/api/projects/:team/tasks/:taskId/runs/:runId/cancel/': async ({ params }) => {
                    cancelledRuns.push(params.runId as string)
                    return [200, {}]
                },
            },
        })

        logic.actions.prewarm(WARM_REQUEST)
        await expectLogic(logic).toMount()
        logic.actions.releaseWarm()
        logic.actions.noteDraft(true, WARM_REQUEST)

        resolveHeldWarm()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.warmLease).toMatchObject({ runId: 'warm-run-1' })
        expect(cancelledRuns).toEqual([])
    })

    it('drops a warm that resolves after the submit consumed it mid-flight', async () => {
        // The scene consumes the warm only after its create resolves, so a create round trip that beats
        // the slower warm POST leaves the warm still in flight at consume time. Without a fence the
        // completing POST installs a lease on a Run the create may have already activated, and a later
        // selection change would then cancel that live Run.
        let resolveHeldWarm: () => void = () => {}
        useMocks({
            post: {
                '/api/projects/:team/tasks/warm/': async () => {
                    await new Promise<void>((resolve) => {
                        resolveHeldWarm = resolve
                    })
                    return [200, { task_id: 'warm-task-1', run_id: 'warm-run-1' }]
                },
                '/api/projects/:team/tasks/:taskId/runs/:runId/cancel/': async ({ params }) => {
                    cancelledRuns.push(params.runId as string)
                    return [200, {}]
                },
            },
        })

        logic.actions.prewarm(WARM_REQUEST)
        await expectLogic(logic).toMount()
        // The submit consumes the warm while the POST is still open.
        logic.actions.consumeWarm()

        resolveHeldWarm()
        await expectLogic(logic).toFinishAllListeners()

        // No lease is installed, so a later selection change (noteDraft only releases when a lease is
        // held) has nothing to cancel — the activated Run is safe. And the Run itself was not cancelled.
        expect(logic.values.warmLease).toBeNull()
        expect(cancelledRuns).toEqual([])
    })

    it('releases a held warm when the composer unmounts', async () => {
        // Navigating away is the common way to leave the composer. Without an unmount release, the warm
        // sandbox idles until the server reaper while holding a scarce per-user warm-pool slot.
        let cancelSeen: () => void = () => {}
        const cancelled = new Promise<void>((resolve) => {
            cancelSeen = resolve
        })
        useMocks({
            post: {
                '/api/projects/:team/tasks/warm/': async () => {
                    warmCalls += 1
                    return [200, { task_id: 'warm-task-1', run_id: 'warm-run-1' }]
                },
                '/api/projects/:team/tasks/:taskId/runs/:runId/cancel/': async ({ params }) => {
                    cancelledRuns.push(params.runId as string)
                    cancelSeen()
                    return [200, {}]
                },
            },
        })

        jest.useFakeTimers()
        logic.actions.noteDraft(true, WARM_REQUEST)
        jest.advanceTimersByTime(300)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.warmLease).toMatchObject({ runId: 'warm-run-1' })

        // Leaving the composer unmounts the logic; the deferred promise resolves only if the cancel fires.
        logic.unmount()
        await cancelled

        expect(cancelledRuns).toEqual(['warm-run-1'])
    })
})
