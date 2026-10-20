import { MOCK_DEFAULT_USER } from 'lib/api.mock'

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

const conditions = [
    {
        key: 'signed_up',
        type: 'behavioral',
        value: 'performed_event_multiple',
        event_type: 'events',
        operator: 'gte',
        operator_value: 1,
        time_value: 14,
        time_interval: 'day',
    },
    { key: 'email', type: 'person', operator: 'icontains', value: '@' },
]
const filtersWith = (values: Record<string, any>[]): Record<string, any> => ({
    properties: { type: 'AND', values: [{ type: 'AND', values }] },
})

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
    cohort_filters: filtersWith(conditions),
}
// What the cohort API stores for the same conditions: defaults filled in and bytecode compiled.
const savedFilters = filtersWith(
    conditions.map((condition) => ({ ...condition, negation: false, bytecode: ['_H', 1], conditionHash: 'abc123' }))
)

describe('broadcastAudienceSuggestionsLogic', () => {
    beforeEach(() => {
        jest.mocked(broadcastAudienceSuggestionsGenerate).mockResolvedValue({
            status: 'ready',
            suggestions: [suggestion],
        })
        jest.mocked(cohortsCreate).mockResolvedValue({ id: 41, name: suggestion.name } as any)
        initKeaTests()
    })

    const minutesAgo = (minutes: number): string => new Date(Date.now() - minutes * 60_000).toISOString()
    const snapshot = (overrides: Record<string, any> = {}): Record<string, any> => ({
        id: 7,
        name: suggestion.name,
        description: suggestion.description,
        deleted: false,
        is_static: true,
        errors_calculating: 0,
        created_by: { uuid: MOCK_DEFAULT_USER.uuid },
        created_at: minutesAgo(10),
        filters: suggestion.cohort_filters,
        ...overrides,
    })

    it.each([
        ['creates a cohort for a new idea', [], 41, 1],
        ["reuses the user's own fresh snapshot of the idea", [snapshot()], 7, 0],
        ['reuses a snapshot whose filters the server filled in', [snapshot({ filters: savedFilters })], 7, 0],
        ['ignores a deleted cohort with the same name', [snapshot({ deleted: true })], 41, 1],
        ['ignores a snapshot whose filters were edited', [snapshot({ filters: { properties: {} } })], 41, 1],
        ['ignores a snapshot over an hour old', [snapshot({ created_at: minutesAgo(61) })], 41, 1],
        ["ignores another user's snapshot", [snapshot({ created_by: { uuid: 'someone-else' } })], 41, 1],
        ['ignores a dynamic cohort with the same name', [snapshot({ is_static: false })], 41, 1],
    ])('%s', async (_name, existing, cohortId, creates) => {
        jest.mocked(cohortsList).mockResolvedValue({ results: existing } as any)
        const logic = broadcastAudienceSuggestionsLogic()
        logic.mount()

        await expectLogic(logic, () => logic.actions.pickSuggestion(suggestion)).toFinishAllListeners()

        expect(cohortsCreate).toHaveBeenCalledTimes(creates)
        if (creates) {
            // A dynamic cohort with event conditions can't be a broadcast audience, so the idea is a static snapshot.
            expect(jest.mocked(cohortsCreate).mock.calls[0][1]).toMatchObject({ is_static: true })
        }
        const audience = JSON.parse(router.values.searchParams[AUDIENCE_PREFILL_PARAM])
        expect(audience).toEqual([expect.objectContaining({ type: 'cohort', value: cohortId })])
        expect(logic.values.creatingId).toBeNull()
    })
})
