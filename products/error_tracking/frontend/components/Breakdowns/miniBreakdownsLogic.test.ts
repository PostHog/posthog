import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { miniBreakdownsLogic } from './miniBreakdownsLogic'

describe('miniBreakdownsLogic', () => {
    let logic: ReturnType<typeof miniBreakdownsLogic.build>

    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/': { results: {} },
            },
        })
        initKeaTests()
        logic = miniBreakdownsLogic({ issueId: 'issue-1' })
        logic.mount()
    })

    afterEach(() => logic?.unmount())

    // There used to be no loadResponseFailure reducer at all, so a failed breakdowns query left
    // response/responseLoading unchanged — indistinguishable from "query returned nothing" and
    // with no way to retry. It must surface the error and clear it on retry.
    it('surfaces and clears a response load failure', () => {
        logic.actions.loadResponseFailure('Failed to load breakdowns')
        expect(logic.values.responseError).toBe('Failed to load breakdowns')

        logic.actions.loadResponse()
        expect(logic.values.responseError).toBeNull()
    })
})
