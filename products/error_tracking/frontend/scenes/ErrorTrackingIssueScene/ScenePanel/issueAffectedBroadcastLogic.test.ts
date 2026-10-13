import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { cohortsCreate } from 'products/cohorts/frontend/generated/api'
import { parseBroadcastAudiencePrefill } from 'products/workflows/frontend/Broadcasts/broadcastAudiencePrefill'
import { workflowPreviousRecipientsCreate } from 'products/workflows/frontend/generated/api'

import { issueAffectedBroadcastLogic } from './issueAffectedBroadcastLogic'

jest.mock('products/cohorts/frontend/generated/api', () => ({
    cohortsCreate: jest.fn(),
}))
jest.mock('products/workflows/frontend/generated/api', () => ({
    workflowPreviousRecipientsCreate: jest.fn(),
    hogFlowsUserBlastRadiusCreate: jest.fn(),
}))

const mockCohortsCreate = jest.mocked(cohortsCreate)
const mockPreviousRecipients = jest.mocked(workflowPreviousRecipientsCreate)

describe('issueAffectedBroadcastLogic', () => {
    beforeEach(() => {
        initKeaTests()
        mockCohortsCreate.mockResolvedValue({ id: 42, name: 'People affected by Checkout timeout' } as never)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        { case: 'nobody was emailed about the issue before', previous: { cohort_id: null, people: 0 }, leftOut: [] },
        {
            case: 'people were emailed about the issue before',
            previous: { cohort_id: 77, people: 3 },
            leftOut: [{ type: 'cohort', key: 'id', value: 77, operator: 'not_in' }],
        },
    ])(
        'saves the affected people as a static cohort and opens a broadcast when $case',
        async ({ previous, leftOut }) => {
            mockPreviousRecipients.mockResolvedValue(previous as never)
            const logic = issueAffectedBroadcastLogic({ issueId: 'issue-1', issueName: 'Checkout timeout' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.createAudience()
            })
                .toDispatchActions(['createAudienceSuccess'])
                .toFinishAllListeners()

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
            expect(mockPreviousRecipients.mock.calls[0][1]).toEqual({
                source_record: 'error_tracking:issue-1',
                cohort_name: 'Already emailed about Checkout timeout',
            })

            const { pathname, searchParams } = router.values.currentLocation
            expect(pathname).toContain('/broadcasts/new')
            expect(searchParams.name).toEqual('We fixed Checkout timeout')
            expect(searchParams.source).toEqual('error_tracking_affected')
            expect(searchParams.source_record).toEqual('error_tracking:issue-1')
            expect(parseBroadcastAudiencePrefill(searchParams.audience)).toMatchObject([
                { type: 'cohort', key: 'id', value: 42 },
                ...leftOut,
            ])
            logic.unmount()
        }
    )
})
