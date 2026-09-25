import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { HogFlow } from './hogflows/types'
import { workflowsLogic } from './workflowsLogic'

// A child environment: its team id differs from the project id (997 in the test setup).
const TEAM_ID = 4242

const WORKFLOW = {
    id: 'wf-1',
    name: 'Welcome series',
    status: 'draft',
    actions: [],
    edges: [],
} as unknown as HogFlow

describe('workflowsLogic', () => {
    let logic: ReturnType<typeof workflowsLogic.build>
    let requests: string[]
    let confirm: () => Promise<void>

    beforeEach(() => {
        requests = []
        const record = ({ request }: { request: Request }): [number, unknown] => {
            requests.push(`${request.method} ${new URL(request.url).pathname}`)
            return request.method === 'DELETE' ? [204, null] : [200, { ...WORKFLOW, results: [WORKFLOW], count: 1 }]
        }
        useMocks({
            get: { '/api/projects/:team_id/hog_flows/': record, '/api/projects/:team_id/hog_flows/:id/': record },
            post: { '/api/projects/:team_id/hog_flows/': record },
            patch: { '/api/projects/:team_id/hog_flows/:id/': record },
            delete: { '/api/projects/:team_id/hog_flows/:id/': record },
        })
        initKeaTests()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: TEAM_ID })
        jest.spyOn(LemonDialog, 'open').mockImplementation((props) => {
            confirm = async () => {
                await (props.primaryButton as { onClick: () => Promise<void> }).onClick()
            }
        })
        router.actions.push(urls.workflows(), { status: 'all' })
        logic = workflowsLogic()
        logic.mount()
        // The table loads the list when it mounts; the logic alone doesn't.
        logic.actions.loadWorkflows()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it.each([
        [
            'archive',
            () => logic.actions.archiveWorkflow(WORKFLOW),
            true,
            `PATCH /api/projects/${TEAM_ID}/hog_flows/wf-1/`,
        ],
        [
            'restore',
            () => logic.actions.restoreWorkflow(WORKFLOW),
            false,
            `PATCH /api/projects/${TEAM_ID}/hog_flows/wf-1/`,
        ],
        [
            'delete',
            () => logic.actions.deleteWorkflow(WORKFLOW),
            true,
            `DELETE /api/projects/${TEAM_ID}/hog_flows/wf-1/`,
        ],
        [
            'toggle',
            () => logic.actions.toggleWorkflowStatus(WORKFLOW),
            false,
            `PATCH /api/projects/${TEAM_ID}/hog_flows/wf-1/`,
        ],
        [
            'duplicate',
            () => logic.actions.duplicateWorkflow(WORKFLOW),
            false,
            `POST /api/projects/${TEAM_ID}/hog_flows/`,
        ],
    ])('%s goes to the team id and reloads the list', async (_, run, confirmFirst, request) => {
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])
        requests = []

        await expectLogic(logic, run).toFinishAllListeners()
        if (confirmFirst) {
            await confirm()
        }
        // The list reloads from the same team once the change lands.
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])

        expect(requests.filter((r) => !r.startsWith('GET'))).toEqual([request])
        expect(requests).toContain(`GET /api/projects/${TEAM_ID}/hog_flows`)
        expect(requests.filter((r) => r.includes('/projects/997/'))).toEqual([])
    })
})
