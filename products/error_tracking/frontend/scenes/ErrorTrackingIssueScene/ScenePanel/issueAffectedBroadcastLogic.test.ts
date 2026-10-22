import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { hogqlQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import { cohortsCreate } from 'products/cohorts/frontend/generated/api'
import { parseBroadcastAudiencePrefill } from 'products/workflows/frontend/Broadcasts/broadcastAudiencePrefill'
import * as messageAudience from 'products/workflows/frontend/MessageAudience/messageAudience'

import { issueAffectedBroadcastLogic } from './issueAffectedBroadcastLogic'

jest.mock('products/cohorts/frontend/generated/api', () => ({
    cohortsCreate: jest.fn(),
}))

jest.mock('~/queries/query', () => ({ hogqlQuery: jest.fn() }))

const mockCohortsCreate = jest.mocked(cohortsCreate)
const mockHogqlQuery = jest.mocked(hogqlQuery)

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

    it.each([
        { scenario: 'people with an email were hit', count: () => Promise.resolve([3, 2]), offered: true },
        { scenario: 'no one hit has an email', count: () => Promise.resolve([3, 0]), offered: false },
        { scenario: 'the count fails', count: () => Promise.reject(new Error('timeout')), offered: false },
    ])('offers the fixed email after resolve only when $scenario', async ({ count, offered }) => {
        jest.spyOn(messageAudience, 'messageAudienceAccessDisabledReason').mockReturnValue(null)
        mockHogqlQuery.mockImplementation(async () => ({ results: [await count()] }) as never)
        const success = jest.spyOn(lemonToast, 'success')
        const logic = issueAffectedBroadcastLogic({ issueId: 'issue-1', issueName: 'Checkout timeout' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.offerAfterResolve()
        }).toFinishAllListeners()

        expect(success).toHaveBeenCalledTimes(offered ? 1 : 0)
        if (offered) {
            success.mock.calls[0][1]?.button?.action?.()
            expect(logic.values.isModalOpen).toBe(true)
            await expectLogic(logic, () => {
                logic.actions.createAudience()
            }).toDispatchActions(['createAudienceSuccess'])
            expect(router.values.currentLocation.searchParams.source).toEqual('error_tracking_resolved')
        }
        logic.unmount()
    })
})
