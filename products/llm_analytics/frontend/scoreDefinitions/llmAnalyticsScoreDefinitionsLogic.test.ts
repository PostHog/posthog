import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { llmAnalyticsScoreDefinitionsList } from '../generated/api'
import type { ScoreDefinitionApi as ScoreDefinition } from '../generated/api.schemas'
import { llmAnalyticsScoreDefinitionsLogic, SCORE_DEFINITIONS_PER_PAGE } from './llmAnalyticsScoreDefinitionsLogic'

jest.mock('../generated/api', () => ({
    llmAnalyticsScoreDefinitionsList: jest.fn(),
}))

const mockLlmAnalyticsScoreDefinitionsList = llmAnalyticsScoreDefinitionsList as jest.MockedFunction<
    typeof llmAnalyticsScoreDefinitionsList
>

const mockScoreDefinition: ScoreDefinition = {
    id: 'score_def_1',
    name: 'Quality',
    description: 'Reusable quality scorer',
    kind: 'categorical',
    archived: false,
    current_version: 2,
    config: {
        options: [
            { key: 'good', label: 'Good' },
            { key: 'bad', label: 'Bad' },
        ],
    },
    created_by: {
        id: 1,
        uuid: 'test-uuid-1',
        distinct_id: 'test-distinct-id-1',
        first_name: 'Test',
        email: 'test@example.com',
        hedgehog_config: null,
    },
    created_at: '2026-03-11T00:00:00Z',
    updated_at: '2026-03-11T00:00:00Z',
    team: MOCK_DEFAULT_TEAM.id,
}

describe('llmAnalyticsScoreDefinitionsLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        mockLlmAnalyticsScoreDefinitionsList.mockResolvedValue({
            results: [mockScoreDefinition],
            count: 1,
            next: null,
            previous: null,
        })
    })

    it('loads score definitions on mount using the default filters', async () => {
        const logic = llmAnalyticsScoreDefinitionsLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(mockLlmAnalyticsScoreDefinitionsList).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            search: undefined,
            kind: undefined,
            archived: false,
            order_by: 'name',
            offset: 0,
            limit: SCORE_DEFINITIONS_PER_PAGE,
        })
    })

    it('updates filters and resets pagination', async () => {
        const logic = llmAnalyticsScoreDefinitionsLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.setFilters({ page: 3 }, false)
            logic.actions.setFilters({ search: 'quality', kind: 'categorical', archived: 'true' })
        }).toFinishAllListeners()

        expect(logic.values.filters).toEqual({
            page: 1,
            search: 'quality',
            kind: 'categorical',
            archived: 'true',
            order_by: 'name',
        })
        expect(mockLlmAnalyticsScoreDefinitionsList).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            search: 'quality',
            kind: 'categorical',
            archived: true,
            order_by: 'name',
            offset: 0,
            limit: SCORE_DEFINITIONS_PER_PAGE,
        })
    })

    it('does not show the empty count label while loading', async () => {
        let resolveRequest: ((value: Awaited<ReturnType<typeof llmAnalyticsScoreDefinitionsList>>) => void) | undefined
        mockLlmAnalyticsScoreDefinitionsList.mockImplementation(
            () =>
                new Promise((resolve) => {
                    resolveRequest = resolve
                })
        )

        const logic = llmAnalyticsScoreDefinitionsLogic()
        logic.mount()

        expect(logic.values.scoreDefinitionsLoading).toBe(true)
        expect(logic.values.scoreDefinitionCountLabel).toBe('')

        resolveRequest?.({
            results: [],
            count: 0,
            next: null,
            previous: null,
        })

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.scoreDefinitionCountLabel).toBe('0 scorers')
    })
})
