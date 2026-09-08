import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { WORKFLOWS_PER_PAGE, workflowsLogic } from './workflowsLogic'

describe('workflowsLogic', () => {
    let logic: ReturnType<typeof workflowsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/': () => [200, { results: [], count: 90 }],
            },
        })
        initKeaTests()
        logic = workflowsLogic()
        logic.mount()
    })

    it.each([
        ['the bare list path', urls.workflows()],
        ['the tab path the scene writes', urls.workflows('workflows')],
    ])('pages forward from %s', async (_name, path) => {
        router.actions.push(path)

        await expectLogic(logic, () => {
            logic.values.pagination.onForward?.()
        }).toMatchValues({
            filters: expect.objectContaining({ page: 2 }),
            paramsFromFilters: expect.objectContaining({ offset: WORKFLOWS_PER_PAGE }),
        })
    })

    it.each([
        ['the bare list path', urls.workflows()],
        ['the tab path the scene writes', urls.workflows('workflows')],
    ])('reads the page from %s', async (_name, path) => {
        await expectLogic(logic, () => {
            router.actions.push(path, { page: '3' })
        }).toMatchValues({
            filters: expect.objectContaining({ page: 3 }),
        })
    })
})
