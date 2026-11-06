import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { workflowLogic } from './workflowLogic'
import { workflowRevisionsLogic } from './workflowRevisionsLogic'

const WORKFLOW_ID = 'wf-revisions-1'

describe('workflowRevisionsLogic', () => {
    let logic: ReturnType<typeof workflowRevisionsLogic.build>
    let restoreBodies: Record<string, any>[]

    beforeEach(() => {
        restoreBodies = []
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': {
                    id: WORKFLOW_ID,
                    name: 'Test',
                    version: 3,
                    status: 'active',
                    actions: [],
                    edges: [],
                    updated_at: '2026-05-01T00:00:00.000Z',
                },
                '/api/projects/:team_id/hog_flows/:id/revisions': {
                    count: 2,
                    results: [
                        { version: 3, created_at: '2026-05-01T00:00:00.000Z', created_by: null },
                        { version: 2, created_at: '2026-04-01T00:00:00.000Z', created_by: null },
                    ],
                },
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
            post: {
                '/api/projects/:team_id/hog_flows/:id/revisions/:version/restore': async ({ request }) => {
                    restoreBodies.push((await request.json()) as Record<string, any>)
                    return [200, { id: WORKFLOW_ID }]
                },
            },
        })
        initKeaTests()
        logic = workflowRevisionsLogic({ id: WORKFLOW_ID })
        logic.mount()
    })

    it('loads revisions on mount', async () => {
        await expectLogic(logic).toDispatchActions(['loadRevisionsSuccess'])
        expect(logic.values.revisions.map((revision) => revision.version)).toEqual([3, 2])
    })

    // Restore must send overwrite (the confirm dialog already warned about replacing a staged
    // draft), rebase the open canvas on the restored draft, and land the user back on it.
    it('confirmRestoreRevision restores with overwrite, reloads the workflow, and navigates to the canvas', async () => {
        const flowLogic = workflowLogic({ id: WORKFLOW_ID })
        flowLogic.mount()
        await expectLogic(flowLogic).toDispatchActions(['loadWorkflowSuccess'])

        await expectLogic(logic, () => {
            logic.actions.confirmRestoreRevision(2, null)
        }).toDispatchActions([flowLogic.actionTypes.loadWorkflow])

        expect(restoreBodies).toEqual([{ overwrite: true, expected_draft_updated_at: null }])
        // The router projects the path under /project/:id.
        expect(router.values.location.pathname).toContain(urls.workflow(WORKFLOW_ID, 'workflow'))
        expect(logic.values.restoringVersion).toBeNull()
    })
})
