import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { traceReviewsApi } from './traceReviewsApi'
import { traceReviewsLazyLoaderLogic } from './traceReviewsLazyLoaderLogic'
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

describe('traceReviewsLazyLoaderLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
    })

    it('loads a batched set of reviews and stores null for missing traces', async () => {
        mockTraceReviewsApi.list.mockResolvedValue({
            results: [mockReview],
            count: 1,
            offset: 0,
        })

        const logic = traceReviewsLazyLoaderLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.ensureReviewsLoaded(['trace_123', 'trace_456'])
        }).toFinishAllListeners()

        expect(mockTraceReviewsApi.list).toHaveBeenCalledWith(
            {
                trace_id__in: ['trace_123', 'trace_456'],
                limit: 2,
            },
            MOCK_DEFAULT_TEAM.id
        )
        expect(logic.values.reviewsByTraceId).toEqual({
            trace_123: mockReview,
            trace_456: null,
        })
    })

    it('only marks uncached traces as loading when a mixed batch is requested', async () => {
        mockTraceReviewsApi.list.mockResolvedValue({
            results: [],
            count: 0,
            offset: 0,
        })

        const logic = traceReviewsLazyLoaderLogic()
        logic.mount()
        logic.actions.loadReviewsBatchSuccess({ trace_123: mockReview }, ['trace_123'])

        await expectLogic(logic, () => {
            logic.actions.ensureReviewsLoaded(['trace_123', 'trace_456'])
        }).toFinishAllListeners()

        expect(mockTraceReviewsApi.list).toHaveBeenLastCalledWith(
            {
                trace_id__in: ['trace_456'],
                limit: 1,
            },
            MOCK_DEFAULT_TEAM.id
        )
        expect(logic.values.isTraceLoading('trace_123')).toBe(false)
        expect(logic.values.getTraceReview('trace_123')).toEqual(mockReview)
        expect(logic.values.getTraceReview('trace_456')).toBeNull()
    })

    it('tracks failed traces separately so they are not cached as unreviewed', async () => {
        mockTraceReviewsApi.list.mockRejectedValueOnce(new Error('nope'))

        const logic = traceReviewsLazyLoaderLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.ensureReviewsLoaded(['trace_123'])
        }).toFinishAllListeners()

        expect(logic.values.getTraceReview('trace_123')).toBeUndefined()
        expect(logic.values.didTraceReviewLoadFail('trace_123')).toBe(true)
        logic.actions.markTraceIdsLoading(['trace_123'])
        expect(logic.values.didTraceReviewLoadFail('trace_123')).toBe(false)
        expect(logic.values.isTraceLoading('trace_123')).toBe(true)
    })
})
