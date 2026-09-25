import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { restoreWorkflowToDraft, setWorkflowStatus } from './workflowRowActions'

describe('workflowRowActions', () => {
    let patches: { id: string; body: unknown }[]

    beforeEach(() => {
        patches = []
        useMocks({
            patch: {
                '/api/projects/:team_id/hog_flows/:id/': async ({ request, params }) => {
                    if (params.id === 'wf-broken') {
                        return [500, { detail: 'Server error' }]
                    }
                    patches.push({ id: String(params.id), body: await request.json() })
                    return [200, {}]
                },
            },
        })
        initKeaTests()
    })

    it.each([
        ['restores a workflow to draft', () => restoreWorkflowToDraft('997', { id: 'wf-1', name: 'Welcome' }), 'draft'],
        ['sets a status', () => setWorkflowStatus('997', { id: 'wf-1', name: 'Welcome' }, 'active'), 'active'],
    ])('%s through the project-scoped endpoint', async (_, run, status) => {
        await expect(run()).resolves.toBe(true)
        expect(patches).toEqual([{ id: 'wf-1', body: { status } }])
    })

    it('reports a failed update and leaves the caller to keep its row', async () => {
        await expect(restoreWorkflowToDraft('997', { id: 'wf-broken', name: 'Broken' })).resolves.toBe(false)
        expect(patches).toEqual([])
    })
})
