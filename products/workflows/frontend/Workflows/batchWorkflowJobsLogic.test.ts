import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlowBatchJobCancelResponseApi } from 'products/workflows/frontend/generated/api.schemas'

import { batchWorkflowJobsLogic } from './batchWorkflowJobsLogic'

const WORKFLOW_ID = 'wf-batch-1'

describe('batchWorkflowJobsLogic', () => {
    let logic: ReturnType<typeof batchWorkflowJobsLogic.build>
    let getCalls: number
    let cancelResponse: HogFlowBatchJobCancelResponseApi

    beforeEach(() => {
        getCalls = 0
        cancelResponse = { status: 'cancelled', marked: 1, remaining: 0, done: true }
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/batch_jobs/': () => {
                    getCalls += 1
                    return [200, []]
                },
            },
            post: {
                '/api/projects/:team_id/hog_flows/:id/batch_jobs/:batch_job_id/cancel/': () => [200, cancelResponse],
            },
        })
        initKeaTests()
        logic = batchWorkflowJobsLogic({ id: WORKFLOW_ID })
        logic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('fetches once when entering the invocations tab', async () => {
        router.actions.push(urls.workflow(WORKFLOW_ID, 'invocations'))
        await expectLogic(logic).toDispatchActions(['loadBatchWorkflowJobsSuccess'])
        expect(getCalls).toBe(1)
    })

    it('fetches on initial mount when the URL is already on the invocations tab (deep link)', async () => {
        // Tear down the logic mounted by the outer beforeEach, then re-mount on the invocations URL
        // so urlToAction fires its afterMount initial-fire while the path already matches.
        logic.unmount()
        router.actions.push(urls.workflow(WORKFLOW_ID, 'invocations'))
        getCalls = 0

        logic = batchWorkflowJobsLogic({ id: WORKFLOW_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadBatchWorkflowJobsSuccess'])
        expect(getCalls).toBe(1)
    })

    // Regression: typing in the invocations search box writes to URL search params on every keystroke.
    // Before the fix, that re-triggered loadBatchWorkflowJobs and unmounted the expanded LemonCollapse.
    it('does not refetch when only the URL search params change on the invocations tab', async () => {
        router.actions.push(urls.workflow(WORKFLOW_ID, 'invocations'))
        await expectLogic(logic).toDispatchActions(['loadBatchWorkflowJobsSuccess'])

        await expectLogic(logic, () => {
            router.actions.push(`${urls.workflow(WORKFLOW_ID, 'invocations')}?search=hi`)
            router.actions.push(`${urls.workflow(WORKFLOW_ID, 'invocations')}?search=hi+there`)
        }).toNotHaveDispatchedActions(['loadBatchWorkflowJobs'])
    })

    it('refetches when navigating away and back to the invocations tab', async () => {
        router.actions.push(urls.workflow(WORKFLOW_ID, 'invocations'))
        await expectLogic(logic).toDispatchActions(['loadBatchWorkflowJobsSuccess'])
        expect(getCalls).toBe(1)

        router.actions.push(urls.workflow(WORKFLOW_ID, 'workflow'))
        router.actions.push(urls.workflow(WORKFLOW_ID, 'invocations'))
        await expectLogic(logic).toDispatchActions(['loadBatchWorkflowJobsSuccess'])
        expect(getCalls).toBe(2)
    })

    // The cancel endpoint returns `done: true` with a non-cancelled status when a completion won the
    // stop race; the toast must reflect the status, not report a stop that didn't happen.
    it.each([
        { case: 'the sweep cancelled the run', status: 'cancelled', done: true, toast: 'success' },
        { case: 'a completion won the stop race', status: 'completed', done: true, toast: 'info' },
        { case: 'runs are still in flight', status: 'active', done: false, toast: 'warning' },
    ] as const)('cancelBatchJob reports "$toast" when $case', async ({ status, done, toast }) => {
        cancelResponse = { status, marked: 0, remaining: done ? 0 : 1, done }
        const successSpy = jest.spyOn(lemonToast, 'success')
        const infoSpy = jest.spyOn(lemonToast, 'info')
        const warningSpy = jest.spyOn(lemonToast, 'warning')

        await expectLogic(logic, () => {
            logic.actions.cancelBatchJob('job-1')
        }).toDispatchActions(['cancelBatchJobComplete'])

        expect(successSpy).toHaveBeenCalledTimes(toast === 'success' ? 1 : 0)
        expect(infoSpy).toHaveBeenCalledTimes(toast === 'info' ? 1 : 0)
        expect(warningSpy).toHaveBeenCalledTimes(toast === 'warning' ? 1 : 0)
    })
})
