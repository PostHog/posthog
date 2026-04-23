import {
    buildReviewExportJsonData,
    buildReviewExportTableData,
    fetchAllReviewsForExport,
    formatScoresSummary,
    getReviewerEmail,
    getReviewerName,
    getTraceAbsoluteUrl,
} from './reviewExportUtils'
import { traceReviewsApi } from './traceReviewsApi'
import type { TraceReview, TraceReviewScore } from './types'

jest.mock('./traceReviewsApi', () => ({
    traceReviewsApi: {
        list: jest.fn(),
    },
}))

describe('reviewExportUtils', () => {
    const categoricalScore: TraceReviewScore = {
        id: 'score-1',
        definition_id: 'definition-1',
        definition_name: 'Helpfulness',
        definition_kind: 'categorical',
        definition_archived: false,
        definition_version_id: 'v1',
        definition_version: 1,
        definition_config: {
            options: [
                { key: 'good', label: 'Good' },
                { key: 'bad', label: 'Bad' },
            ],
            selection_mode: 'single',
        },
        categorical_values: ['good'],
        numeric_value: null,
        boolean_value: null,
        created_at: '2026-04-01T00:00:00Z',
        updated_at: null,
    }

    const numericScore: TraceReviewScore = {
        ...categoricalScore,
        id: 'score-2',
        definition_id: 'definition-2',
        definition_name: 'Quality',
        definition_kind: 'numeric',
        definition_config: {},
        categorical_values: null,
        numeric_value: '4.25',
    }

    const reviewA: TraceReview = {
        id: 'review-a',
        trace_id: 'trace-a',
        comment: 'Great response',
        created_at: '2026-04-01T00:00:00Z',
        updated_at: '2026-04-02T00:00:00Z',
        created_by: null,
        reviewed_by: {
            uuid: 'u1',
            id: 1,
            distinct_id: 'u1',
            first_name: 'Ada',
            last_name: 'Lovelace',
            email: 'ada@example.com',
        },
        scores: [categoricalScore, numericScore],
        team: 1,
    }

    const reviewB: TraceReview = {
        id: 'review-b',
        trace_id: 'trace-b',
        comment: null,
        created_at: '2026-04-03T00:00:00Z',
        updated_at: null,
        created_by: null,
        reviewed_by: null,
        scores: [],
        team: 1,
    }

    describe('getTraceAbsoluteUrl', () => {
        it('combines origin with the project-scoped trace URL', () => {
            const url = getTraceAbsoluteUrl('trace-123', 'https://us.posthog.com')

            expect(url.startsWith('https://us.posthog.com/')).toBe(true)
            expect(url.endsWith('/llm-analytics/traces/trace-123')).toBe(true)
        })
    })

    describe('formatScoresSummary', () => {
        it('renders each score as "Name: Value" joined by semicolons', () => {
            expect(formatScoresSummary(reviewA)).toBe('Helpfulness: Good; Quality: 4.25')
        })

        it('returns an empty string when there are no scores', () => {
            expect(formatScoresSummary(reviewB)).toBe('')
        })
    })

    describe('getReviewerName / getReviewerEmail', () => {
        it('returns first + last name when available', () => {
            expect(getReviewerName(reviewA)).toBe('Ada Lovelace')
            expect(getReviewerEmail(reviewA)).toBe('ada@example.com')
        })

        it('returns empty strings for unreviewed reviews', () => {
            expect(getReviewerName(reviewB)).toBe('')
            expect(getReviewerEmail(reviewB)).toBe('')
        })
    })

    describe('buildReviewExportTableData', () => {
        it('includes core columns plus one column per score definition', () => {
            const rows = buildReviewExportTableData([reviewA, reviewB], 'https://example.posthog.com')
            const [headers, rowA, rowB] = rows

            expect(headers).toEqual([
                'Trace ID',
                'Trace URL',
                'Comment',
                'Reviewer name',
                'Reviewer email',
                'Scores',
                'Created at',
                'Updated at',
                'Score: Helpfulness',
                'Score: Quality',
            ])

            expect(rowA).toEqual([
                'trace-a',
                expect.stringContaining('/llm-analytics/traces/trace-a'),
                'Great response',
                'Ada Lovelace',
                'ada@example.com',
                'Helpfulness: Good; Quality: 4.25',
                '2026-04-01T00:00:00Z',
                '2026-04-02T00:00:00Z',
                'Good',
                '4.25',
            ])

            expect(rowB).toEqual([
                'trace-b',
                expect.stringContaining('/llm-analytics/traces/trace-b'),
                '',
                '',
                '',
                '',
                '2026-04-03T00:00:00Z',
                '',
                '',
                '',
            ])
        })

        it('renders an empty table when no reviews are provided', () => {
            const rows = buildReviewExportTableData([])

            expect(rows).toEqual([
                [
                    'Trace ID',
                    'Trace URL',
                    'Comment',
                    'Reviewer name',
                    'Reviewer email',
                    'Scores',
                    'Created at',
                    'Updated at',
                ],
            ])
        })
    })

    describe('buildReviewExportJsonData', () => {
        it('produces a JSON-friendly structure with a scores map and trace URL', () => {
            const [jsonA] = buildReviewExportJsonData([reviewA], 'https://example.posthog.com')

            expect(jsonA).toMatchObject({
                trace_id: 'trace-a',
                comment: 'Great response',
                reviewer_name: 'Ada Lovelace',
                reviewer_email: 'ada@example.com',
                scores: { Helpfulness: 'Good', Quality: '4.25' },
            })
            expect(typeof jsonA.trace_url).toBe('string')
            expect(String(jsonA.trace_url)).toContain('/llm-analytics/traces/trace-a')
        })
    })

    describe('fetchAllReviewsForExport', () => {
        const listMock = traceReviewsApi.list as jest.Mock

        beforeEach(() => {
            listMock.mockReset()
        })

        it('paginates until all rows are fetched', async () => {
            listMock.mockResolvedValueOnce({ results: [reviewA, reviewB], count: 3, offset: 0 }).mockResolvedValueOnce({
                results: [{ ...reviewA, id: 'review-c', trace_id: 'trace-c' }],
                count: 3,
                offset: 2,
            })

            const { reviews, truncated } = await fetchAllReviewsForExport(
                { search: 'foo' },
                { maxRows: 100, pageSize: 2 }
            )

            expect(reviews).toHaveLength(3)
            expect(truncated).toBe(false)
            expect(listMock).toHaveBeenCalledTimes(2)
            expect(listMock).toHaveBeenNthCalledWith(1, { search: 'foo', offset: 0, limit: 2 })
            expect(listMock).toHaveBeenNthCalledWith(2, { search: 'foo', offset: 2, limit: 2 })
        })

        it('stops early when a short page is returned', async () => {
            listMock.mockResolvedValueOnce({ results: [reviewA], count: 1, offset: 0 })

            const { reviews, truncated } = await fetchAllReviewsForExport({}, { maxRows: 10, pageSize: 5 })

            expect(reviews).toEqual([reviewA])
            expect(truncated).toBe(false)
            expect(listMock).toHaveBeenCalledTimes(1)
        })

        it('reports truncation when the backend has more rows than maxRows', async () => {
            listMock.mockResolvedValue({
                results: [reviewA, reviewB],
                count: 50,
                offset: 0,
            })

            const { reviews, truncated } = await fetchAllReviewsForExport({}, { maxRows: 2, pageSize: 2 })

            expect(reviews).toHaveLength(2)
            expect(truncated).toBe(true)
        })
    })
})
