import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    confirmArchiveWorkflow,
    confirmDeleteWorkflow,
    restoreWorkflowToDraft,
    setWorkflowStatus,
} from './workflowRowActions'

// A child environment's team id differs from its project id; these calls address the team.
const TEAM_ID = '4242'

describe('workflowRowActions', () => {
    let requests: { method: string; path: string; body?: unknown }[]
    let confirm: () => Promise<void>

    beforeEach(() => {
        requests = []
        const respond = async ({
            request,
            params,
        }: {
            request: Request
            params: Record<string, unknown>
        }): Promise<[number, unknown?]> => {
            const body = request.method === 'PATCH' ? await request.json() : undefined
            requests.push({ method: request.method, path: new URL(request.url).pathname, body })
            if (params.id === 'wf-broken') {
                return [500, { detail: 'Server error' }]
            }
            return request.method === 'DELETE' ? [204] : [200, {}]
        }
        useMocks({
            patch: { '/api/projects/:team_id/hog_flows/:id/': respond },
            delete: { '/api/projects/:team_id/hog_flows/:id/': respond },
        })
        initKeaTests()
        jest.spyOn(LemonDialog, 'open').mockImplementation((props) => {
            confirm = async () => {
                await (props.primaryButton as { onClick: () => Promise<void> }).onClick()
            }
        })
        jest.spyOn(lemonToast, 'error')
    })

    afterEach(() => jest.restoreAllMocks())

    it.each([
        [
            'restores a workflow to draft',
            () => restoreWorkflowToDraft(TEAM_ID, { id: 'wf-1', name: 'Welcome' }),
            'draft',
        ],
        ['sets a status', () => setWorkflowStatus(TEAM_ID, { id: 'wf-1', name: 'Welcome' }, 'active'), 'active'],
    ])('%s through the team-scoped endpoint', async (_, run, status) => {
        await expect(run()).resolves.toBe(true)
        expect(requests).toEqual([
            { method: 'PATCH', path: `/api/projects/${TEAM_ID}/hog_flows/wf-1/`, body: { status } },
        ])
    })

    it('reports a failed update and leaves the caller to keep its row', async () => {
        await expect(restoreWorkflowToDraft(TEAM_ID, { id: 'wf-broken', name: 'Broken' })).resolves.toBe(false)
        expect(lemonToast.error).toHaveBeenCalledWith('Failed to restore workflow: Server error')
    })

    it.each([
        [
            'archive',
            (onDone: () => void) => confirmArchiveWorkflow(TEAM_ID, { id: 'wf-1', name: 'Welcome' }, onDone),
            { method: 'PATCH', path: `/api/projects/${TEAM_ID}/hog_flows/wf-1/`, body: { status: 'archived' } },
        ],
        [
            'delete',
            (onDone: () => void) => confirmDeleteWorkflow(TEAM_ID, { id: 'wf-1', name: 'Welcome' }, onDone),
            { method: 'DELETE', path: `/api/projects/${TEAM_ID}/hog_flows/wf-1/`, body: undefined },
        ],
    ])('confirming the %s dialog sends the request, then runs the refresh', async (_, open, request) => {
        const onDone = jest.fn()
        open(onDone)
        expect(requests).toEqual([])

        await confirm()
        expect(requests).toEqual([request])
        expect(onDone).toHaveBeenCalledTimes(1)
    })

    it.each([
        [
            'archive',
            (onDone: () => void) => confirmArchiveWorkflow(TEAM_ID, { id: 'wf-broken', name: 'Broken' }, onDone),
            'Failed to archive workflow: Server error',
        ],
        [
            'delete',
            (onDone: () => void) => confirmDeleteWorkflow(TEAM_ID, { id: 'wf-broken', name: 'Broken' }, onDone),
            'Failed to delete workflow: Server error',
        ],
    ])('a failed %s shows the error and skips the refresh', async (_, open, message) => {
        const onDone = jest.fn()
        open(onDone)
        await confirm()
        expect(lemonToast.error).toHaveBeenCalledWith(message)
        expect(onDone).not.toHaveBeenCalled()
    })
})
