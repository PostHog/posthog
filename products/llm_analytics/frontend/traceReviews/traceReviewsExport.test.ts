import Papa from 'papaparse'

import { lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { copyReviewsAs, getReviewClipboardRows } from './traceReviewsExport'
import type { TraceReview, TraceReviewScore } from './types'

jest.mock('lib/utils/copyToClipboard')
jest.mock('@posthog/lemon-ui', () => ({
    lemonToast: {
        error: jest.fn(),
    },
}))
jest.mock('papaparse', () => ({
    unparse: jest.fn((data: unknown, options: { delimiter?: string } = {}) => {
        const delimiter = options.delimiter || ','
        return `mock-papa-unparse:${delimiter}:${JSON.stringify(data)}`
    }),
}))

const mockCopyToClipboard = copyToClipboard as jest.MockedFunction<typeof copyToClipboard>
const mockLemonToastError = lemonToast.error as jest.MockedFunction<typeof lemonToast.error>
const mockPapaUnparse = Papa.unparse as jest.MockedFunction<typeof Papa.unparse>

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

        it('serializes scores as a JSON string instead of flattening the array', () => {
            const [row] = getReviewClipboardRows([baseReview])

            expect(typeof row.scores).toBe('string')
            expect(JSON.parse(row.scores as string)).toEqual([baseScore])
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

        it('omits fields outside the allow-list (such as id and team)', () => {
            const [row] = getReviewClipboardRows([baseReview])

            expect(row).not.toHaveProperty('id')
            expect(row).not.toHaveProperty('team')
        })
    })

    describe('copyReviewsAs', () => {
        it('shows an error toast and skips the clipboard write when there are no reviews', async () => {
            await copyReviewsAs([], 'csv')

            expect(mockLemonToastError).toHaveBeenCalledWith('No reviews to copy!')
            expect(mockCopyToClipboard).not.toHaveBeenCalled()
            expect(mockPapaUnparse).not.toHaveBeenCalled()
        })

        it.each([
            ['csv', undefined, 'mock-papa-unparse:,:'],
            ['tsv', { delimiter: '\t' }, 'mock-papa-unparse:\t:'],
        ] as const)(
            'copies %s via Papa.unparse with the matching options',
            async (format, expectedOptions, expectedPrefix) => {
                await copyReviewsAs([baseReview], format)

                expect(mockPapaUnparse).toHaveBeenCalledTimes(1)
                const [rowsArg, optionsArg] = mockPapaUnparse.mock.calls[0]
                expect(rowsArg).toHaveLength(1)
                expect(optionsArg).toEqual(expectedOptions)
                expect(mockCopyToClipboard).toHaveBeenCalledWith(expect.stringContaining(expectedPrefix), 'reviews')
            }
        )

        it('copies JSON as a pretty-printed string and skips Papa.unparse', async () => {
            await copyReviewsAs([baseReview], 'json')

            expect(mockPapaUnparse).not.toHaveBeenCalled()
            expect(mockCopyToClipboard).toHaveBeenCalledTimes(1)
            const [payload, label] = mockCopyToClipboard.mock.calls[0]
            expect(label).toBe('reviews')
            const parsed = JSON.parse(payload as string)
            expect(Array.isArray(parsed)).toBe(true)
            expect(parsed[0].trace_id).toBe('trace-abc')
            expect(payload).toContain('\n    ')
        })

        it.each([
            [
                'synchronous',
                () => {
                    mockCopyToClipboard.mockImplementationOnce(() => {
                        throw new Error('clipboard unavailable')
                    })
                },
            ],
            [
                'asynchronous',
                () => {
                    mockCopyToClipboard.mockRejectedValueOnce(new Error('clipboard rejected'))
                },
            ],
        ] as const)('falls back to an error toast when copying fails (%s)', async (_label, primeFailure) => {
            primeFailure()

            await copyReviewsAs([baseReview], 'json')

            expect(mockLemonToastError).toHaveBeenCalledWith('Copy failed!')
        })
    })
})
