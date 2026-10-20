import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlow } from './hogflows/types'
import { workflowsLogic } from './workflowsLogic'
import { workflowsWaitingRefreshLogic } from './workflowsWaitingRefreshLogic'

const waitingRow = { id: 'wf-waiting', name: 'Welcome', status: 'waiting_for_domain' } as HogFlow
const draftRow = { id: 'wf-draft', name: 'Follow up', status: 'draft' } as HogFlow

describe('workflowsWaitingRefreshLogic', () => {
    let listLogic: ReturnType<typeof workflowsLogic.build>
    let logic: ReturnType<typeof workflowsWaitingRefreshLogic.build>
    let listedRows: HogFlow[]
    let listCount: number

    beforeEach(async () => {
        listCount = 0
        listedRows = [waitingRow, draftRow]
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/': () => {
                    listCount += 1
                    return [200, { results: listedRows, count: listedRows.length }]
                },
            },
        })
        jest.useFakeTimers({ advanceTimers: true })
        initKeaTests()
        listLogic = workflowsLogic()
        listLogic.mount()
        logic = workflowsWaitingRefreshLogic()
        logic.mount()
        await expectLogic(listLogic, () => {
            listLogic.actions.loadWorkflows()
        }).toDispatchActions(['loadWorkflowsSuccess'])
        listCount = 0
    })

    afterEach(() => {
        logic.unmount()
        listLogic.unmount()
        jest.useRealTimers()
    })

    it('refreshes the list while a workflow waits, and stops once none waits', async () => {
        listedRows = [{ ...waitingRow, status: 'active' }, draftRow]

        await jest.advanceTimersByTimeAsync(10_000)
        await expectLogic(logic).toFinishAllListeners()

        expect(listLogic.values.workflows.results.map(({ status }) => status)).toEqual(['active', 'draft'])

        await jest.advanceTimersByTimeAsync(60_000)
        expect(listCount).toEqual(1)
    })
})
