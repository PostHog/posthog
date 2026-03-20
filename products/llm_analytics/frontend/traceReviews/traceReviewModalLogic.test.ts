import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn(), info: jest.fn() },
}))

import { initKeaTests } from '~/test/init'

import { llmAnalyticsScoreDefinitionsList } from '../generated/api'
import type { ScoreDefinitionApi as ScoreDefinition } from '../generated/api.schemas'
import { traceReviewModalLogic } from './traceReviewModalLogic'
import { traceReviewsApi } from './traceReviewsApi'
import { traceReviewsLazyLoaderLogic } from './traceReviewsLazyLoaderLogic'
import type { TraceReview } from './types'

jest.mock('../generated/api', () => ({
    llmAnalyticsScoreDefinitionsList: jest.fn(),
}))

jest.mock('./traceReviewsApi', () => ({
    traceReviewsApi: {
        getByTraceId: jest.fn(),
        save: jest.fn(),
        delete: jest.fn(),
    },
}))

const mockLlmAnalyticsScoreDefinitionsList = llmAnalyticsScoreDefinitionsList as jest.MockedFunction<
    typeof llmAnalyticsScoreDefinitionsList
>
const mockTraceReviewsApi = traceReviewsApi as jest.Mocked<typeof traceReviewsApi>

describe('traceReviewModalLogic', () => {
    const booleanDefinition: ScoreDefinition = {
        id: 'score_def_1',
        name: 'Hallucination',
        description: 'Whether the model hallucinated.',
        kind: 'boolean',
        archived: false,
        current_version: 1,
        config: {
            true_label: 'Yes',
            false_label: 'No',
        },
        created_by: null,
        created_at: '2026-03-12T00:00:00Z',
        updated_at: '2026-03-12T00:00:00Z',
        team: MOCK_DEFAULT_TEAM.id,
    }

    const numericDefinition: ScoreDefinition = {
        id: 'score_def_2',
        name: 'Accuracy',
        description: 'How accurate the response was.',
        kind: 'numeric',
        archived: false,
        current_version: 1,
        config: {
            min: 0,
            max: 10,
            step: 1,
        },
        created_by: null,
        created_at: '2026-03-12T00:00:00Z',
        updated_at: '2026-03-12T00:00:00Z',
        team: MOCK_DEFAULT_TEAM.id,
    }

    const existingReview: TraceReview = {
        id: 'review_1',
        trace_id: 'trace_1',
        comment: 'Needs investigation',
        created_at: '2026-03-12T00:00:00Z',
        updated_at: '2026-03-12T00:00:00Z',
        created_by: null,
        reviewed_by: null,
        team: MOCK_DEFAULT_TEAM.id,
        scores: [
            {
                id: 'score_1',
                definition_id: booleanDefinition.id,
                definition_name: booleanDefinition.name,
                definition_kind: booleanDefinition.kind,
                definition_archived: false,
                definition_version_id: 'version_1',
                definition_version: 1,
                definition_config: booleanDefinition.config,
                categorical_values: null,
                numeric_value: null,
                boolean_value: true,
                created_at: '2026-03-12T00:00:00Z',
                updated_at: '2026-03-12T00:00:00Z',
            },
        ],
    }

    beforeEach(() => {
        initKeaTests()
        traceReviewsLazyLoaderLogic.mount()
        jest.resetAllMocks()
    })

    it('keeps the modal in loading state until the review and scorers finish loading', async () => {
        let resolveReview: ((value: Awaited<ReturnType<typeof traceReviewsApi.getByTraceId>>) => void) | undefined
        let resolveDefinitions:
            | ((value: Awaited<ReturnType<typeof llmAnalyticsScoreDefinitionsList>>) => void)
            | undefined

        mockTraceReviewsApi.getByTraceId.mockImplementation(
            () =>
                new Promise((resolve) => {
                    resolveReview = resolve
                })
        )
        mockLlmAnalyticsScoreDefinitionsList.mockImplementation(
            () =>
                new Promise((resolve) => {
                    resolveDefinitions = resolve
                })
        )

        const logic = traceReviewModalLogic({ traceId: 'trace_1' })
        logic.mount()

        logic.actions.openModal()

        expect(logic.values.modalDataLoading).toBe(true)
        expect(logic.values.loadedDefinitions).toEqual([])

        resolveReview?.(null)
        resolveDefinitions?.({
            results: [booleanDefinition],
            count: 1,
            next: null,
            previous: null,
        })

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.modalDataLoading).toBe(false)
        expect(logic.values.loadedDefinitions).toEqual([booleanDefinition])
    })

    it('loads the first page of active scorers for the current team and populates the existing review values', async () => {
        mockTraceReviewsApi.getByTraceId.mockResolvedValue(existingReview)
        mockLlmAnalyticsScoreDefinitionsList.mockResolvedValue({
            results: [booleanDefinition],
            count: 1,
            next: null,
            previous: null,
        })

        const logic = traceReviewModalLogic({ traceId: 'trace_1' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.openModal()
        }).toFinishAllListeners()

        expect(mockTraceReviewsApi.getByTraceId).toHaveBeenCalledWith('trace_1', MOCK_DEFAULT_TEAM.id)
        expect(mockLlmAnalyticsScoreDefinitionsList).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            archived: false,
            order_by: 'name',
            search: undefined,
            offset: 0,
            limit: 50,
        })
        expect(logic.values.currentReview).toEqual(existingReview)
        expect(logic.values.loadedDefinitions).toEqual([booleanDefinition])
        expect(logic.values.selectedDefinitions).toEqual([booleanDefinition])
        expect(logic.values.scoreValues[booleanDefinition.id]).toBe(true)
        expect(logic.values.comment).toBe('Needs investigation')
    })

    it('only submits scorers that are explicitly selected', async () => {
        mockTraceReviewsApi.getByTraceId.mockResolvedValue(existingReview)
        mockLlmAnalyticsScoreDefinitionsList.mockResolvedValue({
            results: [booleanDefinition, numericDefinition],
            count: 2,
            next: null,
            previous: null,
        })

        const logic = traceReviewModalLogic({ traceId: 'trace_1' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.openModal()
        }).toFinishAllListeners()

        expect(logic.values.selectedDefinitions).toEqual([booleanDefinition])

        logic.actions.selectDefinition(numericDefinition)
        logic.actions.setScoreValue(numericDefinition.id, '8')
        logic.actions.removeSelectedDefinition(booleanDefinition.id)

        expect(logic.values.selectedDefinitions).toEqual([numericDefinition])
        expect(logic.values.submitPayload).toEqual({
            trace_id: 'trace_1',
            comment: 'Needs investigation',
            scores: [
                {
                    definition_id: numericDefinition.id,
                    numeric_value: '8',
                },
            ],
        })
    })

    it('includes queue context in the save payload when opened from a queue', async () => {
        mockTraceReviewsApi.getByTraceId.mockResolvedValue(null)
        mockLlmAnalyticsScoreDefinitionsList.mockResolvedValue({
            results: [booleanDefinition],
            count: 1,
            next: null,
            previous: null,
        })

        const logic = traceReviewModalLogic({ traceId: 'trace_1', queueId: 'queue_1' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.openModal()
        }).toFinishAllListeners()

        expect(logic.values.submitPayload).toEqual({
            trace_id: 'trace_1',
            queue_id: 'queue_1',
            comment: null,
            scores: [],
        })
    })

    it('keeps selected scorers pinned while the picker search results change', async () => {
        mockTraceReviewsApi.getByTraceId.mockResolvedValue(null)
        mockLlmAnalyticsScoreDefinitionsList
            .mockResolvedValueOnce({
                results: [booleanDefinition, numericDefinition],
                count: 2,
                next: null,
                previous: null,
            })
            .mockResolvedValueOnce({
                results: [],
                count: 0,
                next: null,
                previous: null,
            })

        const logic = traceReviewModalLogic({ traceId: 'trace_1' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.openModal()
        }).toFinishAllListeners()

        logic.actions.selectDefinition(numericDefinition)

        await expectLogic(logic, () => {
            logic.actions.setDefinitionSearch('zzz')
        }).toFinishAllListeners()

        expect(logic.values.loadedDefinitions).toEqual([])
        expect(logic.values.selectedDefinitions).toEqual([numericDefinition])
    })

    it('loads more scorers when requested', async () => {
        mockTraceReviewsApi.getByTraceId.mockResolvedValue(null)
        mockLlmAnalyticsScoreDefinitionsList
            .mockResolvedValueOnce({
                results: [booleanDefinition],
                count: 2,
                next: 'next-page',
                previous: null,
            })
            .mockResolvedValueOnce({
                results: [numericDefinition],
                count: 2,
                next: null,
                previous: null,
            })

        const logic = traceReviewModalLogic({ traceId: 'trace_1' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.openModal()
        }).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.loadMoreDefinitions()
        }).toFinishAllListeners()

        expect(mockLlmAnalyticsScoreDefinitionsList).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            archived: false,
            order_by: 'name',
            search: undefined,
            offset: 1,
            limit: 50,
        })
        expect(logic.values.loadedDefinitions).toEqual([booleanDefinition, numericDefinition])
    })
})
