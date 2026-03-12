import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { llmAnalyticsScoreDefinitionsCreate, llmAnalyticsScoreDefinitionsList } from '../generated/api'
import type { ScoreDefinitionApi as ScoreDefinition } from '../generated/api.schemas'
import { llmAnalyticsScoreDefinitionsLogic } from './llmAnalyticsScoreDefinitionsLogic'
import { scoreDefinitionModalLogic } from './scoreDefinitionModalLogic'
jest.mock('../generated/api', () => ({
    llmAnalyticsScoreDefinitionsList: jest.fn(),
    llmAnalyticsScoreDefinitionsCreate: jest.fn(),
    llmAnalyticsScoreDefinitionsNewVersionCreate: jest.fn(),
    llmAnalyticsScoreDefinitionsPartialUpdate: jest.fn(),
}))

const mockLlmAnalyticsScoreDefinitionsList = llmAnalyticsScoreDefinitionsList as jest.MockedFunction<
    typeof llmAnalyticsScoreDefinitionsList
>
const mockLlmAnalyticsScoreDefinitionsCreate = llmAnalyticsScoreDefinitionsCreate as jest.MockedFunction<
    typeof llmAnalyticsScoreDefinitionsCreate
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
    created_by: null,
    created_at: '2026-03-11T00:00:00Z',
    updated_at: '2026-03-11T00:00:00Z',
    team: MOCK_DEFAULT_TEAM.id,
}

describe('scoreDefinitionModalLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        mockLlmAnalyticsScoreDefinitionsList.mockResolvedValue({
            results: [mockScoreDefinition],
            count: 1,
            next: null,
            previous: null,
        })
        mockLlmAnalyticsScoreDefinitionsCreate.mockResolvedValue(mockScoreDefinition)
    })

    it('submits a create flow and closes the modal via the parent logic', async () => {
        const listLogic = llmAnalyticsScoreDefinitionsLogic()
        listLogic.mount()

        await expectLogic(listLogic).toFinishAllListeners()

        listLogic.actions.openModal('create')

        const modalLogic = scoreDefinitionModalLogic({
            tabId: undefined,
            mode: 'create',
            scoreDefinition: null,
        })
        modalLogic.mount()

        modalLogic.actions.setDraftField('name', 'New quality scorer')

        await expectLogic(modalLogic, () => {
            modalLogic.actions.submit()
        }).toFinishAllListeners()

        expect(mockLlmAnalyticsScoreDefinitionsCreate).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            name: 'New quality scorer',
            description: '',
            kind: 'categorical',
            config: {
                options: [
                    { key: 'good', label: 'Good' },
                    { key: 'bad', label: 'Bad' },
                ],
            },
        })
        expect(mockLlmAnalyticsScoreDefinitionsList).toHaveBeenCalledTimes(2)
        expect(listLogic.values.modalMode).toBeNull()
        expect(modalLogic.values.submitting).toBe(false)
    })

    it('stores the modal draft in logic', async () => {
        const modalLogic = scoreDefinitionModalLogic({
            tabId: undefined,
            mode: 'create',
            scoreDefinition: null,
        })
        modalLogic.mount()

        modalLogic.actions.setDraftField('name', 'Hallucination')
        modalLogic.actions.setDraftField('kind', 'boolean')
        modalLogic.actions.setDraftField('trueLabel', 'Hallucinated')
        modalLogic.actions.addOption()
        modalLogic.actions.updateOptionLabel(0, 'Helpful')
        modalLogic.actions.removeOption(2)

        expect(modalLogic.values.draft.name).toBe('Hallucination')
        expect(modalLogic.values.draft.kind).toBe('boolean')
        expect(modalLogic.values.draft.trueLabel).toBe('Hallucinated')
        expect(modalLogic.values.draft.options).toEqual([
            { key: 'good', label: 'Helpful' },
            { key: 'bad', label: 'Bad' },
        ])
    })

    it('initializes edit config from the saved scorer config', () => {
        const customOptions = [
            { key: 'animals', label: 'Animals' },
            { key: 'finance', label: 'Finance' },
            { key: 'science', label: 'Science' },
        ]
        const modalLogic = scoreDefinitionModalLogic({
            tabId: undefined,
            mode: 'config',
            scoreDefinition: {
                ...mockScoreDefinition,
                config: {
                    options: customOptions,
                    selection_mode: 'multiple',
                    min_selections: 1,
                    max_selections: 2,
                },
            },
        })
        modalLogic.mount()

        expect(modalLogic.values.draft.options).toEqual(customOptions)
        expect(modalLogic.values.draft.selectionMode).toBe('multiple')
        expect(modalLogic.values.draft.categoricalMinSelections).toBe('1')
        expect(modalLogic.values.draft.categoricalMaxSelections).toBe('2')
    })
})
