import Papa from 'papaparse'

import { traceReviewsApi, type TraceReviewListFilters } from './traceReviewsApi'
import {
    CLIPBOARD_ROW_LIMIT,
    fetchAllReviewsForExport,
    formatReviewsForClipboard,
    getReviewClipboardRows,
} from './traceReviewsExport'
import type { TraceReview, TraceReviewScore } from './types'

jest.mock('papaparse', () => ({
    unparse: jest.fn((data: unknown, options: { delimiter?: string } = {}) => {
        const delimiter = options.delimiter || ','
        return `mock-papa-unparse:${delimiter}:${JSON.stringify(data)}`
    }),
}))
jest.mock('./traceReviewsApi', () => ({
    ...jest.requireActual('./traceReviewsApi'),
    traceReviewsApi: {
        list: jest.fn(),
    },
}))

const mockPapaUnparse = Papa.unparse as jest.MockedFunction<typeof Papa.unparse>
const mockTraceReviewsList = traceReviewsApi.list as jest.MockedFunction<typeof traceReviewsApi.list>

const filters: TraceReviewListFilters = {
    search: 'auth',
    definition_id: 'def-1',
    order_by: '-updated_at',
}

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
    trace_id: 'trace-abc',
    trace_url: 'https://us.posthog.com/project/1/llm-analytics/traces/trace-abc',
    comment: 'Looks good',
    created_at: '2026-03-12T00:00:00Z',
    updated_at: '2026-03-12T01:00:00Z',
    created_by: {
        id: 7,
        uuid: 'user-uuid-7',
        distinct_id: 'distinct-7',
        first_name: 'Ada',
        last_name: 'Lovelace',
        email: 'ada@example.com',
    },
    reviewed_by: {
        id: 8,
        uuid: 'user-uuid-8',
        distinct_id: 'distinct-8',
        first_name: 'Grace',
        last_name: 'Hopper',
        email: 'grace@example.com',
    },
    scores: [baseScore],
    team: 1,
}

describe('traceReviewsExport', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('getReviewClipboardRows', () => {
        it('returns an empty array when no reviews are passed', () => {
            expect(getReviewClipboardRows([])).toEqual([])
        })

        it('flattens nested user objects with column-prefixed keys', () => {
            const [row] = getReviewClipboardRows([baseReview])

            expect(row['reviewed_by.email']).toBe('grace@example.com')
            expect(row['reviewed_by.first_name']).toBe('Grace')
            expect(row['created_by.email']).toBe('ada@example.com')
            expect(row).not.toHaveProperty('reviewed_by')
            expect(row).not.toHaveProperty('created_by')
        })

        it('expands score arrays into indexed dotted keys mirroring rest_framework_csv', () => {
            const [row] = getReviewClipboardRows([baseReview])

            expect(row['scores.0.id']).toBe('score-1')
            expect(row['scores.0.definition_id']).toBe('definition-1')
            expect(row['scores.0.definition_name']).toBe('Helpfulness')
            expect(row['scores.0.categorical_values.0']).toBe('good')
            expect(row['scores.0.definition_config.selection_mode']).toBe('single')
            expect(row['scores.0.definition_config.options.0.key']).toBe('good')
            expect(row['scores.0.definition_config.options.0.label']).toBe('Good')
            expect(row).not.toHaveProperty('scores')
        })

        it('produces ragged columns when reviews have different score counts (matches server-side)', () => {
            const reviewWithTwoScores: TraceReview = {
                ...baseReview,
                id: 'review-2',
                scores: [baseScore, { ...baseScore, id: 'score-2', definition_name: 'Accuracy' }],
            }
            const [single, double] = getReviewClipboardRows([baseReview, reviewWithTwoScores])

            expect(single['scores.0.id']).toBe('score-1')
            expect(single).not.toHaveProperty('scores.1.id')

            expect(double['scores.0.id']).toBe('score-1')
            expect(double['scores.1.id']).toBe('score-2')
            expect(double['scores.1.definition_name']).toBe('Accuracy')
        })

        it('copies primitive review fields as-is', () => {
            const [row] = getReviewClipboardRows([baseReview])

            expect(row.trace_id).toBe('trace-abc')
            expect(row.comment).toBe('Looks good')
            expect(row.created_at).toBe('2026-03-12T00:00:00Z')
            expect(row.updated_at).toBe('2026-03-12T01:00:00Z')
        })

        it('includes the absolute trace URL alongside the trace_id', () => {
            const [row] = getReviewClipboardRows([baseReview])

            expect(row.trace_url).toBe('https://us.posthog.com/project/1/llm-analytics/traces/trace-abc')
        })

        it('preserves null user fields without throwing', () => {
            const review: TraceReview = {
                ...baseReview,
                created_by: null,
                reviewed_by: null,
            }

            const [row] = getReviewClipboardRows([review])

            expect(row.reviewed_by).toBeNull()
            expect(row.created_by).toBeNull()
        })

        it('mirrors the file-export shape by including every serializer field (id, team, ...)', () => {
            const [row] = getReviewClipboardRows([baseReview])

            expect(row.id).toBe('review-1')
            expect(row.team).toBe(1)
        })
    })

    describe('fetchAllReviewsForExport', () => {
        it('paginates until the full dataset is fetched', async () => {
            const reviewA = { ...baseReview, id: 'a' }
            const reviewB = { ...baseReview, id: 'b' }
            const reviewC = { ...baseReview, id: 'c' }
            mockTraceReviewsList
                .mockResolvedValueOnce({ results: [reviewA, reviewB], count: 3 })
                .mockResolvedValueOnce({ results: [reviewC], count: 3 })

            const result = await fetchAllReviewsForExport(filters)

            expect(mockTraceReviewsList).toHaveBeenCalledTimes(2)
            expect(mockTraceReviewsList.mock.calls[0][0]).toMatchObject({
                search: 'auth',
                definition_id: 'def-1',
                order_by: '-updated_at',
                offset: 0,
            })
            expect(mockTraceReviewsList.mock.calls[1][0]).toMatchObject({ offset: 2 })
            expect(result.reviews.map((r) => r.id)).toEqual(['a', 'b', 'c'])
            expect(result.total).toBe(3)
            expect(result.truncated).toBe(false)
        })

        it('flags the result as truncated when count exceeds the cap and skips further pages', async () => {
            mockTraceReviewsList.mockResolvedValueOnce({
                results: [baseReview],
                count: CLIPBOARD_ROW_LIMIT + 1,
            })

            const result = await fetchAllReviewsForExport(filters)

            expect(mockTraceReviewsList).toHaveBeenCalledTimes(1)
            expect(result.truncated).toBe(true)
            expect(result.total).toBe(CLIPBOARD_ROW_LIMIT + 1)
        })

        it('treats blank filter values as undefined when calling the API', async () => {
            mockTraceReviewsList.mockResolvedValueOnce({ results: [], count: 0 })

            await fetchAllReviewsForExport({ search: '', definition_id: '', order_by: '-updated_at' })

            expect(mockTraceReviewsList.mock.calls[0][0]).toMatchObject({
                search: undefined,
                definition_id: undefined,
                order_by: '-updated_at',
            })
        })
    })

    describe('formatReviewsForClipboard', () => {
        it.each([
            ['csv', undefined, 'mock-papa-unparse:,:'],
            ['tsv', { delimiter: '\t' }, 'mock-papa-unparse:\t:'],
        ] as const)(
            'formats %s via Papa.unparse with the matching options',
            (format, expectedOptions, expectedPrefix) => {
                const payload = formatReviewsForClipboard([baseReview], format)

                expect(mockPapaUnparse).toHaveBeenCalledTimes(1)
                const [rowsArg, optionsArg] = mockPapaUnparse.mock.calls[0]
                expect(rowsArg).toHaveLength(1)
                expect(optionsArg).toEqual(expectedOptions)
                expect(payload).toContain(expectedPrefix)
            }
        )

        it('formats JSON as the nested API shape, not the flattened CSV shape', () => {
            const payload = formatReviewsForClipboard([baseReview], 'json')

            expect(mockPapaUnparse).not.toHaveBeenCalled()
            const parsed = JSON.parse(payload)
            expect(Array.isArray(parsed)).toBe(true)
            expect(parsed[0]).toEqual(baseReview)
            expect(parsed[0].scores[0].id).toBe('score-1')
            expect(parsed[0].created_by.email).toBe('ada@example.com')
            expect(payload).toContain('\n    ')
        })
    })
})
