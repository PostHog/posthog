import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import { traceReviewModalLogic } from './traceReviewModalLogic'
import { traceReviewsApi } from './traceReviewsApi'
import { traceReviewsLazyLoaderLogic } from './traceReviewsLazyLoaderLogic'
import type { TraceReview } from './types'

jest.mock('./traceReviewsApi')
jest.mock('lib/lemon-ui/LemonToast/LemonToast')

const mockTraceReviewsApi = traceReviewsApi as jest.Mocked<typeof traceReviewsApi>

const mockReview: TraceReview = {
    id: 'review_1',
    trace_id: 'trace_123',
    score_kind: 'label',
    score_label: 'bad',
    score_numeric: null,
    comment: 'Missed the constraint',
    created_at: '2026-03-10T00:00:00Z',
    updated_at: '2026-03-10T00:00:00Z',
    created_by: null,
    reviewed_by: null,
    team: MOCK_DEFAULT_TEAM.id,
}

describe('traceReviewModalLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
    })

    it('loads the existing review when the modal opens', async () => {
        mockTraceReviewsApi.getByTraceId.mockResolvedValue(mockReview)

        const lazyLoaderLogic = traceReviewsLazyLoaderLogic()
        lazyLoaderLogic.mount()

        const logic = traceReviewModalLogic({ traceId: 'trace_123' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.openModal()
        }).toFinishAllListeners()

        expect(logic.values.currentReview).toEqual(mockReview)
        expect(logic.values.scoreMode).toBe('label')
        expect(logic.values.scoreLabel).toBe('bad')
        expect(logic.values.comment).toBe('Missed the constraint')
        expect(lazyLoaderLogic.values.getTraceReview('trace_123')).toEqual(mockReview)
    })

    it('saves a review without requiring a score or comment', async () => {
        const savedReview = {
            ...mockReview,
            score_kind: null,
            score_label: null,
            comment: null,
        }

        mockTraceReviewsApi.getByTraceId.mockResolvedValue(null)
        mockTraceReviewsApi.save.mockResolvedValue(savedReview)

        const lazyLoaderLogic = traceReviewsLazyLoaderLogic()
        lazyLoaderLogic.mount()

        const logic = traceReviewModalLogic({ traceId: 'trace_123' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.openModal()
        }).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.saveCurrentReview()
        }).toFinishAllListeners()

        expect(mockTraceReviewsApi.save).toHaveBeenCalledWith(
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
        expect(lemonToast.success).toHaveBeenCalledWith('Trace review saved.')
        expect(lazyLoaderLogic.values.getTraceReview('trace_123')).toEqual(savedReview)
    })

    it('removes an existing review', async () => {
        mockTraceReviewsApi.getByTraceId.mockResolvedValue(mockReview)
        mockTraceReviewsApi.delete.mockResolvedValue(undefined)

        const lazyLoaderLogic = traceReviewsLazyLoaderLogic()
        lazyLoaderLogic.mount()

        const logic = traceReviewModalLogic({ traceId: 'trace_123' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.openModal()
        }).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.removeCurrentReview()
        }).toFinishAllListeners()

        expect(mockTraceReviewsApi.delete).toHaveBeenCalledWith('review_1', MOCK_DEFAULT_TEAM.id)
        expect(logic.values.currentReview).toBeNull()
        expect(lemonToast.info).toHaveBeenCalledWith('Trace review removed.')
        expect(lazyLoaderLogic.values.getTraceReview('trace_123')).toBeNull()
    })
})
