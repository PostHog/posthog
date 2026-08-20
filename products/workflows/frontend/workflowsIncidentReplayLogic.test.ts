import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { workflowsIncidentReplayLogic } from './workflowsIncidentReplayLogic'

const AFFECTED_FLOW_ID = '019d244c-42c9-0000-ec6c-752c8b265c4f'
const DELETED_FLOW_ID = '019d9146-223a-0000-8165-1a3489e88b3d'
const FLAKY_FLOW_ID = '019f3834-8dbd-0000-4b19-073031109b21'

describe('workflowsIncidentReplayLogic', () => {
    let logic: ReturnType<typeof workflowsIncidentReplayLogic.build>
    let remainingCount: number

    beforeEach(() => {
        remainingCount = 12
        useMocks({
            post: {
                '/api/environments/:team_id/query/:query_kind/': () => [
                    200,
                    {
                        results: [
                            [224, AFFECTED_FLOW_ID],
                            [29, FLAKY_FLOW_ID],
                            [3, DELETED_FLOW_ID],
                        ],
                    },
                ],
            },
            get: {
                '/api/projects/:team_id/hog_flows/:id/': (req) => {
                    if (req.params.id === AFFECTED_FLOW_ID) {
                        return [200, { id: AFFECTED_FLOW_ID, name: 'Order confirmation', user_access_level: 'editor' }]
                    }
                    if (req.params.id === FLAKY_FLOW_ID) {
                        return [500, { detail: 'Internal server error.' }]
                    }
                    return [404, { detail: 'Not found.' }]
                },
                '/api/projects/:team_id/hog_flows/:id/invocation_results_count/': () => [
                    200,
                    { count: remainingCount },
                ],
            },
        })
        initKeaTests()
        logic = workflowsIncidentReplayLogic()
        logic.mount()
    })

    it('resolves workflows by id, drops 404s, keeps rows whose retrieve fails transiently', async () => {
        await expectLogic(logic, () => logic.actions.loadAffectedWorkflows()).toDispatchActions([
            'loadAffectedWorkflowsSuccess',
        ])
        expect(logic.values.affectedWorkflows).toEqual([
            { id: AFFECTED_FLOW_ID, name: 'Order confirmation', failedCount: 12, userAccessLevel: 'editor' },
            { id: FLAKY_FLOW_ID, name: '', failedCount: 12, userAccessLevel: null },
        ])
    })

    it('drops workflows whose remaining failed count is zero', async () => {
        remainingCount = 0
        await expectLogic(logic, () => logic.actions.loadAffectedWorkflows()).toDispatchActions([
            'loadAffectedWorkflowsSuccess',
        ])
        expect(logic.values.affectedWorkflows).toEqual([])
    })
})
