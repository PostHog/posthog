import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { workflowEmailActivityLogic } from './workflowEmailActivityLogic'

const LOG = '/api/projects/:team_id/workflow_email_log/'
const SEND = { invocation_id: 'run-1', action_id: 'welcome', distinct_id: 'user-1', sent_at: '2026-03-10T09:00:00Z' }

describe('workflowEmailActivityLogic', () => {
    let detailStatus: number
    let activityRequests: string[]

    beforeEach(() => {
        detailStatus = 200
        activityRequests = []
        useMocks({
            get: {
                [`${LOG}:id/`]: () => (detailStatus === 200 ? [200, SEND] : [detailStatus, { detail: 'nope' }]),
                [`${LOG}:id/activity/`]: ({ request }) => {
                    activityRequests.push(new URL(request.url).searchParams.get('action_id') ?? '')
                    return [
                        200,
                        { before: [], after: [{ uuid: 'ev-1' }], has_more_before: false, has_more_after: false },
                    ]
                },
            },
            post: { '/api/environments/:team_id/query/:kind/': () => [200, { results: [] }] },
        })
        initKeaTests()
    })

    it.each([
        { name: 'a send with engagement events', status: 200, email: SEND, emailFailed: false, loadsActivity: true },
        {
            name: 'a send with no engagement events',
            status: 404,
            email: null,
            emailFailed: false,
            loadsActivity: false,
        },
        { name: 'a failed lookup', status: 500, email: null, emailFailed: true, loadsActivity: false },
    ])('handles $name', async ({ status, email, emailFailed, loadsActivity }) => {
        detailStatus = status
        const logic = workflowEmailActivityLogic({ invocationId: 'run-1', actionId: 'welcome' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.emailFailed).toBe(emailFailed)
        expect(logic.values.email).toEqual(email)
        expect(activityRequests).toEqual(loadsActivity ? ['welcome'] : [])
    })
})
