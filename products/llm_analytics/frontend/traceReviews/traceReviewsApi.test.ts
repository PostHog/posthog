import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import api, { ApiError } from '~/lib/api'

import { traceReviewsApi } from './traceReviewsApi'
import type { TraceReview } from './types'

jest.mock('~/lib/api')

const mockApi = api as jest.Mocked<typeof api>

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
    team: 2,
}

describe('traceReviewsApi', () => {
    beforeEach(() => {
        jest.resetAllMocks()
    })

    it('lists reviews with trace_id__in filters', async () => {
        jest.spyOn(mockApi, 'get').mockResolvedValue({ results: [mockReview], count: 1, offset: 0 } as any)

        await traceReviewsApi.list({ trace_id__in: ['trace_123', 'trace_456'], limit: 2 }, MOCK_DEFAULT_TEAM.id)

        expect(mockApi.get).toHaveBeenCalledWith(
            `/api/environments/${MOCK_DEFAULT_TEAM.id}/llm_analytics/trace_reviews/?trace_id__in=trace_123%2Ctrace_456&limit=2`
        )
    })

    it('returns the first matching review when fetching by trace id', async () => {
        jest.spyOn(mockApi, 'get').mockResolvedValue({ results: [mockReview], count: 1, offset: 0 } as any)

        await expect(traceReviewsApi.getByTraceId('trace_123', MOCK_DEFAULT_TEAM.id)).resolves.toEqual(mockReview)
    })

    it('retries create as patch when another review is created first', async () => {
        jest.spyOn(mockApi, 'create').mockRejectedValue({ data: { trace_id: ['duplicate'] } })
        jest.spyOn(mockApi, 'get').mockResolvedValue({ results: [mockReview], count: 1, offset: 0 } as any)
        jest.spyOn(mockApi, 'update').mockResolvedValue(mockReview as any)

        await expect(
            traceReviewsApi.save(
                {
                    trace_id: 'trace_123',
                    score_kind: 'label',
                    score_label: 'good',
                    score_numeric: null,
                    comment: null,
                },
                null,
                MOCK_DEFAULT_TEAM.id
            )
        ).resolves.toEqual(mockReview)

        expect(mockApi.create).toHaveBeenCalledWith(
            `/api/environments/${MOCK_DEFAULT_TEAM.id}/llm_analytics/trace_reviews/`,
            {
                trace_id: 'trace_123',
                score_kind: 'label',
                score_label: 'good',
                score_numeric: null,
                comment: null,
            }
        )
        expect(mockApi.update).toHaveBeenCalledWith(
            `/api/environments/${MOCK_DEFAULT_TEAM.id}/llm_analytics/trace_reviews/review_1/`,
            {
                score_kind: 'label',
                score_label: 'good',
                score_numeric: null,
                comment: null,
            }
        )
    })

    it('rethrows create errors that are not duplicate-review conflicts', async () => {
        const apiError = new ApiError('bad request', 400, undefined, { comment: ['too long'] })
        jest.spyOn(mockApi, 'create').mockRejectedValue(apiError)

        await expect(
            traceReviewsApi.save(
                {
                    trace_id: 'trace_123',
                    score_kind: null,
                    score_label: null,
                    score_numeric: null,
                    comment: null,
                },
                null,
                MOCK_DEFAULT_TEAM.id
            )
        ).rejects.toBe(apiError)

        expect(mockApi.get).not.toHaveBeenCalled()
        expect(mockApi.update).not.toHaveBeenCalled()
    })
})
