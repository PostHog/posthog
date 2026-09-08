import { cleanup, fireEvent, render } from '@testing-library/react'
import { Provider, useValues } from 'kea'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { WORKFLOWS_PER_PAGE, workflowsLogic } from './workflowsLogic'

// Mirrors how the table wires the logic's pagination value into the control, so the test clicks the
// same button a user clicks.
function WorkflowsPagination(): JSX.Element {
    const { workflows, pagination } = useValues(workflowsLogic)
    return <PaginationControl {...usePagination(workflows.results, pagination)} />
}

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

    afterEach(() => {
        cleanup()
    })

    function clickNextPage(): void {
        const { container } = render(
            <Provider>
                <WorkflowsPagination />
            </Provider>
        )
        const buttons = container.querySelectorAll<HTMLButtonElement>('.PaginationControl button')
        fireEvent.click(buttons[buttons.length - 1])
    }

    it.each([
        ['the bare list path', urls.workflows()],
        ['the tab path the scene writes', urls.workflows('workflows')],
    ])('pages forward from %s', async (_name, path) => {
        router.actions.push(path)
        // The table loads on mount, so the count the control needs is in place before the first click.
        await expectLogic(logic, () => {
            logic.actions.loadWorkflows()
        }).toDispatchActions(['loadWorkflowsSuccess'])

        clickNextPage()

        await expectLogic(logic).toMatchValues({
            filters: expect.objectContaining({ page: 2 }),
            paramsFromFilters: expect.objectContaining({ offset: WORKFLOWS_PER_PAGE }),
        })
        expect(router.values.searchParams['page']).toBe(2)
        // Paging is a navigation step, so Back has to return to the previous page instead of leaving the list.
        expect(router.values.lastMethod).toBe('PUSH')
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
