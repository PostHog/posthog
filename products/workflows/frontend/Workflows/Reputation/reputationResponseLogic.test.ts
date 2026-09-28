import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TeamEmailReputationResponseApi } from 'products/workflows/frontend/generated/api.schemas'

import { HEALTHY, reputationMocks } from './reputationFixtures'
import { reputationResponseLogic } from './reputationResponseLogic'

describe('reputationResponseLogic', () => {
    let logic: ReturnType<typeof reputationResponseLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        ['every signal is healthy', HEALTHY, true, true],
        [
            // One bounce in 8 sends would read as 12.5%, so the all-clear must not vouch for it.
            'the only provider sent too little to judge',
            { ...HEALTHY, isps: [{ ...HEALTHY.isps[0], emails_sent: 8, bounce_rate: 0 }] },
            true,
            false,
        ],
        [
            'there is no email at all',
            { ...HEALTHY, reputation: null, workflows: [], isps: [] } as TeamEmailReputationResponseApi,
            false,
            false,
        ],
    ])('judges what it can when %s', async (_, response, hasSendingData, hasJudgedProviders) => {
        useMocks(reputationMocks(response))
        logic = reputationResponseLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadReputationSuccess'])

        expect(logic.values.hasSendingData).toBe(hasSendingData)
        expect(logic.values.hasJudgedProviders).toBe(hasJudgedProviders)
    })

    it.each([
        [403, 'forbidden'],
        [500, 'failed'],
    ])('tells a %s apart when the page fails to load', async (status, loadError) => {
        useMocks({ get: { '/api/projects/:team_id/hog_flows/reputation/': [status, { detail: 'Nope' }] } })
        logic = reputationResponseLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadReputationFailure'])

        expect(logic.values.reputationLoadError).toEqual(loadError)
    })
})
