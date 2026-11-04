import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from '@posthog/lemon-ui'

import { deleteFromTree } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { HogFlow } from './hogflows/types'
import { workflowsLogic } from './workflowsLogic'

jest.mock('~/layout/panel-layout/ProjectTree/projectTreeLogic', () => ({
    ...jest.requireActual('~/layout/panel-layout/ProjectTree/projectTreeLogic'),
    deleteFromTree: jest.fn(),
}))

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

    it('drops only the workflows the server deleted from the project tree', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/hog_flows/bulk_delete/': () => [
                    200,
                    { deleted: 1, deleted_ids: ['flow-deleted'] },
                ],
            },
        })
        const openDialog = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
        logic.actions.toggleArchivedWorkflowSelection('flow-deleted')
        logic.actions.toggleArchivedWorkflowSelection('flow-restored-meanwhile')

        logic.actions.deleteSelectedWorkflows()
        await openDialog.mock.calls[0][0].primaryButton?.onClick?.({} as React.MouseEvent<HTMLButtonElement>)

        expect(deleteFromTree).toHaveBeenCalledTimes(1)
        expect(deleteFromTree).toHaveBeenCalledWith('hog_flow', 'flow-deleted')
    })

    it('saves a row tag edit with only the tags, and shows the name the server stored', async () => {
        const workflow = { id: 'flow-1', name: 'Churn win-back', tags: [] } as unknown as HogFlow
        const bodies: unknown[] = []
        useMocks({
            patch: {
                '/api/projects/:team_id/hog_flows/:id/': async ({ request }) => {
                    bodies.push(await request.json())
                    return [200, { ...workflow, tags: ['growth'] }]
                },
            },
        })

        await expectLogic(logic, () => logic.actions.updateWorkflowTags(workflow, ['Growth']))
            .toFinishAllListeners()
            .toMatchValues({ localWorkflowTags: { 'flow-1': ['growth'] } })

        expect(bodies).toEqual([{ tags: ['Growth'] }])
    })

    it("sends a row's next tag save only after the one before it lands", async () => {
        const workflow = { id: 'flow-1', name: 'Churn win-back', tags: [] } as unknown as HogFlow
        const bodies: string[][] = []
        let markFirstInFlight = (): void => {}
        let releaseFirst = (): void => {}
        const firstInFlight = new Promise<void>((resolve) => (markFirstInFlight = resolve))
        const firstReleased = new Promise<void>((resolve) => (releaseFirst = resolve))
        let started = 0
        useMocks({
            patch: {
                '/api/projects/:team_id/hog_flows/:id/': async ({ request }) => {
                    const { tags } = (await request.json()) as { tags: string[] }
                    started += 1
                    if (started === 1) {
                        markFirstInFlight()
                        await firstReleased
                    }
                    bodies.push(tags)
                    return [200, { ...workflow, tags }]
                },
            },
        })

        logic.actions.updateWorkflowTags(workflow, ['growth'])
        logic.actions.updateWorkflowTags(workflow, ['growth', 'billing'])
        await firstInFlight
        releaseFirst()
        await expectLogic(logic).toFinishAllListeners()

        expect(bodies).toEqual([['growth'], ['growth', 'billing']])
        expect(logic.values.localWorkflowTags).toEqual({ 'flow-1': ['growth', 'billing'] })
    })

    it('parses a url whose only filter is a tag', () => {
        router.actions.push(`/workflows?tags=${encodeURIComponent('["growth"]')}`)

        expect(logic.values.filters.tags).toEqual(['growth'])
    })

    it('keeps the filters when a link back to the list carries no query params', () => {
        router.actions.push('/workflows?status=active&type=messaging')
        expect(logic.values.filters.status).toEqual('active')

        router.actions.push('/workflows')

        expect(logic.values.filters.status).toEqual('active')
        expect(logic.values.filters.type).toEqual('messaging')
        expect(router.values.searchParams).toMatchObject({ status: 'active', type: 'messaging' })
    })
})
