import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { llmAnalyticsReviewsLogic, TRACE_REVIEWS_PER_PAGE } from './llmAnalyticsReviewsLogic'
import { traceReviewsApi } from './traceReviewsApi'
import type { TraceReview } from './types'

jest.mock('./traceReviewsApi')

const mockTraceReviewsApi = traceReviewsApi as jest.Mocked<typeof traceReviewsApi>

const mockReview: TraceReview = {
    id: 'review_1',
    trace_id: 'trace_123',
    score_kind: 'label',
    score_label: 'good',
    score_numeric: null,
    comment: 'Looks good',
    created_at: '2026-03-10T00:00:00Z',
    updated_at: '2026-03-10T00:00:00Z',
    created_by: null,
    reviewed_by: null,
    team: MOCK_DEFAULT_TEAM.id,
}

describe('llmAnalyticsReviewsLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        mockTraceReviewsApi.list.mockResolvedValue({
            results: [mockReview],
            count: 1,
            offset: 0,
        })
    })

    it('loads reviews on mount using the default filters', async () => {
        const logic = llmAnalyticsReviewsLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(mockTraceReviewsApi.list).toHaveBeenCalledWith({
            search: '',
            order_by: '-updated_at',
            offset: 0,
            limit: TRACE_REVIEWS_PER_PAGE,
        })
    })

    it('updates the search filter and resets pagination', async () => {
        const logic = llmAnalyticsReviewsLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.setFilters({ page: 3 }, false)
            logic.actions.setFilters({ search: 'hallucination' })
        }).toFinishAllListeners()

        expect(logic.values.filters).toEqual({
            page: 1,
            search: 'hallucination',
            order_by: '-updated_at',
        })
        expect(mockTraceReviewsApi.list).toHaveBeenLastCalledWith({
            search: 'hallucination',
            order_by: '-updated_at',
            offset: 0,
            limit: TRACE_REVIEWS_PER_PAGE,
        })
    })
})
