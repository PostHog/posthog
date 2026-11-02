import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import type { TeamType } from '~/types'

import { errorTrackingSuppressionRulesCreate } from '../../generated/api'
import { suppressSimilarIssuesLogic } from './suppressSimilarIssuesLogic'

jest.mock('../../generated/api', () => ({
    errorTrackingSuppressionRulesCreate: jest.fn(),
}))

const mockSuppressionRulesCreate = jest.mocked(errorTrackingSuppressionRulesCreate)

const CHILD_ENVIRONMENT: TeamType = { ...MOCK_DEFAULT_TEAM, id: MOCK_TEAM_ID + 1, project_id: MOCK_TEAM_ID }

describe('suppressSimilarIssuesLogic', () => {
    let logic: ReturnType<typeof suppressSimilarIssuesLogic.build>

    beforeEach(() => {
        initKeaTests(true, CHILD_ENVIRONMENT)
        jest.spyOn(api, 'query').mockResolvedValue({ results: [[0, 0]] } as never)
        mockSuppressionRulesCreate.mockResolvedValue({} as never)
        logic = suppressSimilarIssuesLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('creates rules in the current environment, not in its parent project', async () => {
        logic.actions.openSuggestion([
            { id: 'issue-1', exceptionType: 'Error', exceptionMessage: 'Request failed with status code 503' },
        ])

        await expectLogic(logic, () => {
            logic.actions.createRules()
        }).toDispatchActions(['createRulesSuccess'])

        expect(mockSuppressionRulesCreate).toHaveBeenCalledWith(
            String(CHILD_ENVIRONMENT.id),
            expect.objectContaining({ sampling_rate: 1 })
        )
    })
})
