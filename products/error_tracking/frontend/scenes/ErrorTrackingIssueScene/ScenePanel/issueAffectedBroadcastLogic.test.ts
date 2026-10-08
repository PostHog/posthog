import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { cohortsCreate } from 'products/cohorts/frontend/generated/api'
import { parseBroadcastAudiencePrefill } from 'products/workflows/frontend/Broadcasts/broadcastAudiencePrefill'

import { issueAffectedBroadcastLogic } from './issueAffectedBroadcastLogic'

jest.mock('products/cohorts/frontend/generated/api', () => ({
    cohortsCreate: jest.fn(),
}))

const mockCohortsCreate = jest.mocked(cohortsCreate)

describe('issueAffectedBroadcastLogic', () => {
    beforeEach(() => {
        initKeaTests()
        mockCohortsCreate.mockResolvedValue({ id: 42, name: 'People affected by Checkout timeout' } as never)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('saves the affected people as a static cohort and opens a broadcast to it', async () => {
        const logic = issueAffectedBroadcastLogic({ issueId: 'issue-1', issueName: 'Checkout timeout' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.createAudience()
        }).toDispatchActions(['createAudienceSuccess'])

        const body = mockCohortsCreate.mock.calls[0][1]
        expect(body).toMatchObject({
            name: 'People affected by Checkout timeout',
            is_static: true,
            query: {
                query: expect.stringMatching(
                    /^SELECT DISTINCT person_id FROM events WHERE event = '\$exception' AND issue_id = 'issue-1'/
                ),
            },
        })

        const { pathname, searchParams } = router.values.currentLocation
        expect(pathname).toContain('/broadcasts/new')
        expect(searchParams.name).toEqual('We fixed Checkout timeout')
        expect(searchParams.source).toEqual('error_tracking_affected')
        expect(parseBroadcastAudiencePrefill(searchParams.audience)).toMatchObject([
            { type: 'cohort', key: 'id', value: 42 },
        ])
        logic.unmount()
    })
})
