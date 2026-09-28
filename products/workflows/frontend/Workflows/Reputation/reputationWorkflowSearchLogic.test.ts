import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { reputationActionListLogic } from './reputationActionListLogic'
import { NEEDS_WORK, reputationMocks } from './reputationFixtures'
import { reputationResponseLogic } from './reputationResponseLogic'
import { reputationWorkflowSearchLogic } from './reputationWorkflowSearchLogic'

describe('reputationWorkflowSearchLogic', () => {
    let logic: ReturnType<typeof reputationWorkflowSearchLogic.build>

    beforeEach(async () => {
        initKeaTests()
        useMocks(reputationMocks(NEEDS_WORK))
        logic = reputationWorkflowSearchLogic()
        logic.mount()
        await expectLogic(reputationResponseLogic).toDispatchActions(['loadReputationSuccess'])
        jest.useFakeTimers()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    async function search(term: string): Promise<void> {
        logic.actions.setSearch(term)
        await jest.advanceTimersByTimeAsync(250)
    }

    it('keeps the action list when a search narrows the workflow table', async () => {
        const listLogic = reputationActionListLogic()
        listLogic.mount()
        const actionKeys = listLogic.values.reputationActions.map((item) => item.key)

        await search('onboarding')
        await expectLogic(logic).toDispatchActions(['searchWorkflowsSuccess'])

        expect(logic.values.tableWorkflows.map((w) => w.hog_flow_id)).toEqual(['wf-onboarding'])
        expect(listLogic.values.reputationActions.map((item) => item.key)).toEqual(actionKeys)
        listLogic.unmount()
    })

    it('shows the table as loading until the typed search has answered', async () => {
        await search('onboarding')
        await expectLogic(logic).toDispatchActions(['searchWorkflowsSuccess'])

        logic.actions.setSearch('win')

        expect(logic.values.tableLoading).toBe(true)
        expect(logic.values.tableWorkflows).toEqual([])
        await jest.advanceTimersByTimeAsync(250)
        await expectLogic(logic).toDispatchActions(['searchWorkflowsSuccess'])
        expect(logic.values.tableLoading).toBe(false)
        expect(logic.values.tableWorkflows.map((w) => w.hog_flow_id)).toEqual(['wf-win-back'])
    })

    it('says so when a search fails instead of keeping stale rows', async () => {
        useMocks({ get: { '/api/projects/:team_id/hog_flows/reputation/': [500, { detail: 'Nope' }] } })

        await search('onboarding')
        await expectLogic(logic).toDispatchActions(['searchWorkflowsSuccess'])

        expect(logic.values.tableWorkflows).toEqual([])
        expect(logic.values.workflowSearchFailed).toBe(true)
        expect(logic.values.tableLoading).toBe(false)
    })
})
