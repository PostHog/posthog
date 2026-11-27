import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aeoBrandsList, aeoPromptsOverview, aeoPromptsRankings } from '../generated/api'
import { aiVisibilityFirstResultsLogic } from './aiVisibilityFirstResultsLogic'

jest.mock('../generated/api', () => ({
    aeoPromptsOverview: jest.fn(async () => ({})),
    aeoPromptsRankings: jest.fn(async () => ({})),
    aeoBrandsList: jest.fn(async () => ({ count: 0, next: null, previous: null, results: [] })),
    aeoBrandsCompetitorCandidates: jest.fn(async () => []),
}))

describe('aiVisibilityFirstResultsLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    it('reads only the answers to the current prompts, so a reset leaves the previous site out', async () => {
        const logic = aiVisibilityFirstResultsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFirstResultsSuccess'])

        const team = String(MOCK_DEFAULT_TEAM.id)
        expect(jest.mocked(aeoPromptsOverview).mock.calls).toEqual([
            [team, { branded: 'non_branded', current_prompts: true }],
            [team, { branded: 'branded', current_prompts: true }],
        ])
        expect(aeoPromptsRankings).toHaveBeenCalledWith(team, { branded: 'non_branded', current_prompts: true })
        expect(aeoBrandsList).toHaveBeenCalled()
        logic.unmount()
    })
})
