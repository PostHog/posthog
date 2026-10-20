import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { HogFlow } from './hogflows/types'
import { workflowsLogic } from './workflowsLogic'

describe('workflowsLogic', () => {
    let logic: ReturnType<typeof workflowsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/': { results: [], count: 0 },
                '/api/projects/:team_id/hog_flows/': { results: [], count: 0 },
            },
        })
        initKeaTests()
        logic = workflowsLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it.each(['/workflows', '/workflows/workflows'])('fills the filters from the query params on %s', (path) => {
        router.actions.push(
            `${path}?created_by=user-uuid&status=active&trigger_type=event&type=messaging&tags=${encodeURIComponent('["growth","billing"]')}`
        )

        expect(logic.values.filters).toEqual({
            search: '',
            createdBy: 'user-uuid',
            status: 'active',
            type: 'messaging',
            triggerType: 'event',
            tags: ['growth', 'billing'],
            page: 1,
        })
    })

    it('saves a row tag edit with only the tags, so it never overwrites the workflow content', async () => {
        const workflow = { id: 'flow-1', name: 'Churn win-back', tags: [] } as unknown as HogFlow
        const update = jest.spyOn(api.hogFlows, 'updateHogFlow').mockResolvedValue(workflow)

        await expectLogic(logic, () => logic.actions.updateWorkflowTags(workflow, ['growth']))
            .toFinishAllListeners()
            .toMatchValues({ localWorkflowTags: { 'flow-1': ['growth'] } })

        expect(update).toHaveBeenCalledWith('flow-1', { tags: ['growth'] })
    })
})
