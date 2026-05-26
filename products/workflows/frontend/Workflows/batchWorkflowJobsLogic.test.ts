import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { batchWorkflowJobsLogic } from './batchWorkflowJobsLogic'

const WORKFLOW_ID = 'wf-batch-1'

describe('batchWorkflowJobsLogic', () => {
    let logic: ReturnType<typeof batchWorkflowJobsLogic.build>
    let getCalls: number

    beforeEach(() => {
        getCalls = 0
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/batch_jobs/': () => {
                    getCalls += 1
                    return [200, []]
                },
            },
        })
        initKeaTests()
        logic = batchWorkflowJobsLogic({ id: WORKFLOW_ID })
        logic.mount()
    })

    it('fetches once when entering the logs tab', async () => {
        router.actions.push(urls.workflow(WORKFLOW_ID, 'logs'))
        await expectLogic(logic).toDispatchActions(['loadBatchWorkflowJobsSuccess'])
        expect(getCalls).toBe(1)
    })

    it('fetches on initial mount when the URL is already on the logs tab (deep link)', async () => {
        // Tear down the logic mounted by the outer beforeEach, then re-mount on the logs URL
        // so urlToAction fires its afterMount initial-fire while the path already matches.
        logic.unmount()
        router.actions.push(urls.workflow(WORKFLOW_ID, 'logs'))
        getCalls = 0

        logic = batchWorkflowJobsLogic({ id: WORKFLOW_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadBatchWorkflowJobsSuccess'])
        expect(getCalls).toBe(1)
    })

    // Regression: typing in the LogsViewer search box writes to URL search params on every keystroke.
    // Before the fix, that re-triggered loadBatchWorkflowJobs and unmounted the expanded LemonCollapse.
    it('does not refetch when only the URL search params change on the logs tab', async () => {
        router.actions.push(urls.workflow(WORKFLOW_ID, 'logs'))
        await expectLogic(logic).toDispatchActions(['loadBatchWorkflowJobsSuccess'])

        await expectLogic(logic, () => {
            router.actions.push(`${urls.workflow(WORKFLOW_ID, 'logs')}?search=hi`)
            router.actions.push(`${urls.workflow(WORKFLOW_ID, 'logs')}?search=hi+there`)
        }).toNotHaveDispatchedActions(['loadBatchWorkflowJobs'])
    })

    it('refetches when navigating away and back to the logs tab', async () => {
        router.actions.push(urls.workflow(WORKFLOW_ID, 'logs'))
        await expectLogic(logic).toDispatchActions(['loadBatchWorkflowJobsSuccess'])
        expect(getCalls).toBe(1)

        router.actions.push(urls.workflow(WORKFLOW_ID, 'workflow'))
        router.actions.push(urls.workflow(WORKFLOW_ID, 'logs'))
        await expectLogic(logic).toDispatchActions(['loadBatchWorkflowJobsSuccess'])
        expect(getCalls).toBe(2)
    })
})
