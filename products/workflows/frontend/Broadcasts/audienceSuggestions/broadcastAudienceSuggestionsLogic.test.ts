import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { cohortsCreate, cohortsList } from 'products/cohorts/frontend/generated/api'

import { broadcastAudienceSuggestionsGenerate } from '../../generated/api'
import type { AudienceSuggestionApi } from '../../generated/api.schemas'
import { AUDIENCE_PREFILL_PARAM } from '../broadcastAudiencePrefill'
import { broadcastAudienceSuggestionsLogic } from './broadcastAudienceSuggestionsLogic'

jest.mock('../../generated/api', () => ({
    broadcastAudienceSuggestionsCurrent: jest.fn(),
    broadcastAudienceSuggestionsGenerate: jest.fn(),
}))
jest.mock('products/cohorts/frontend/generated/api', () => ({
    cohortsCreate: jest.fn(),
    cohortsList: jest.fn(),
}))

const suggestion: AudienceSuggestionApi = {
    id: 'suggestion-1',
    name: 'Signed up, no project yet',
    description: 'People who signed up but never created a project.',
    reason: 'A nudge helps them start.',
    kind: 'not_yet' as AudienceSuggestionApi['kind'],
    event: 'signed_up',
    missing_event: 'project_created',
    window_days: 14,
    min_count: null,
    reachable_count: 34,
    cohort_filters: { properties: { type: 'AND', values: [] } },
}

describe('broadcastAudienceSuggestionsLogic', () => {
    beforeEach(() => {
        jest.mocked(broadcastAudienceSuggestionsGenerate).mockResolvedValue({
            status: 'ready',
            suggestions: [suggestion],
        })
        jest.mocked(cohortsCreate).mockResolvedValue({ id: 41, name: suggestion.name } as any)
        initKeaTests()
    })

    it.each([
        ['creates a cohort for a new idea', [], 41, 1],
        [
            'reuses the cohort of an idea someone already picked',
            [{ id: 7, name: suggestion.name, description: suggestion.description, deleted: false }],
            7,
            0,
        ],
        [
            'ignores a deleted cohort with the same name',
            [{ id: 7, name: suggestion.name, description: suggestion.description, deleted: true }],
            41,
            1,
        ],
    ])('%s', async (_name, existing, cohortId, creates) => {
        jest.mocked(cohortsList).mockResolvedValue({ results: existing } as any)
        const logic = broadcastAudienceSuggestionsLogic()
        logic.mount()

        await expectLogic(logic, () => logic.actions.pickSuggestion(suggestion)).toFinishAllListeners()

        expect(cohortsCreate).toHaveBeenCalledTimes(creates)
        const audience = JSON.parse(router.values.searchParams[AUDIENCE_PREFILL_PARAM])
        expect(audience).toEqual([expect.objectContaining({ type: 'cohort', value: cohortId })])
        expect(logic.values.creatingId).toBeNull()
    })
})
