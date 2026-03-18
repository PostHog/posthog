import type { TraceReview, TraceReviewScore } from './types'
import {
    getHiddenTraceReviewScoreCount,
    getTraceReviewDisplayValue,
    getTraceReviewScoreDisplayValue,
    getTraceReviewScoreTagLabel,
    getTraceReviewScores,
    getVisibleTraceReviewScores,
} from './utils'

describe('traceReviews utils', () => {
    const baseScore: TraceReviewScore = {
        id: 'score-1',
        definition_id: 'definition-1',
        definition_name: 'Helpfulness',
        definition_kind: 'categorical',
        definition_archived: false,
        definition_version_id: 'version-1',
        definition_version: 1,
        definition_config: {
            options: [{ key: 'good', label: 'Good' }],
            selection_mode: 'single',
        },
        categorical_values: ['good'],
        numeric_value: null,
        boolean_value: null,
        created_at: '2026-03-12T00:00:00Z',
        updated_at: null,
    }

    const baseReview: TraceReview = {
        id: 'review-1',
        trace_id: 'trace-1',
        comment: null,
        created_at: '2026-03-12T00:00:00Z',
        updated_at: null,
        created_by: null,
        reviewed_by: null,
        scores: [baseScore],
        team: 1,
    }

    describe('getTraceReviewScores', () => {
        it('falls back to an empty array when scores is missing', () => {
            const review = { ...baseReview, scores: undefined } as unknown as TraceReview

            expect(getTraceReviewScores(review)).toEqual([])
        })
    })

    describe('getTraceReviewDisplayValue', () => {
        it('falls back to Reviewed when scores is missing', () => {
            const review = { ...baseReview, scores: undefined } as unknown as TraceReview

            expect(getTraceReviewDisplayValue(review)).toBe('Reviewed')
        })
    })

    describe('getTraceReviewScoreDisplayValue', () => {
        it('falls back to the selected categorical key when config is malformed', () => {
            const score = { ...baseScore, definition_config: null } as unknown as TraceReviewScore

            expect(getTraceReviewScoreDisplayValue(score)).toBe('good')
        })
    })

    describe('score visibility helpers', () => {
        it('returns visible scores and the hidden count for compact display', () => {
            const extraScore = {
                ...baseScore,
                id: 'score-2',
                definition_id: 'definition-2',
                definition_name: 'Safety',
            }
            const review = { ...baseReview, scores: [baseScore, extraScore] }

            expect(getTraceReviewScoreTagLabel(baseScore)).toBe('Helpfulness: Good')
            expect(getVisibleTraceReviewScores(review, 1)).toEqual([baseScore])
            expect(getHiddenTraceReviewScoreCount(review, 1)).toBe(1)
        })
    })
})
