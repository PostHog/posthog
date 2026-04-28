import Papa from 'papaparse'

import { lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { flattenObject } from '~/queries/nodes/DataTable/clipboardUtils'

import type { TraceReview } from './types'

export type ReviewClipboardFormat = 'csv' | 'json' | 'tsv'

export const REVIEW_CLIPBOARD_COLUMNS = [
    'trace_id',
    'trace_url',
    'comment',
    'scores',
    'reviewed_by',
    'created_by',
    'created_at',
    'updated_at',
] as const

export function getReviewClipboardRows(reviews: TraceReview[]): Record<string, unknown>[] {
    return reviews.map((review) => {
        const flattened: Record<string, unknown> = {}
        for (const col of REVIEW_CLIPBOARD_COLUMNS) {
            const value = review[col]
            if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
                Object.assign(flattened, flattenObject(value, col))
            } else if (Array.isArray(value)) {
                flattened[col] = JSON.stringify(value)
            } else {
                flattened[col] = value
            }
        }
        return flattened
    })
}

export function copyReviewsAs(reviews: TraceReview[], format: ReviewClipboardFormat): void {
    try {
        if (reviews.length === 0) {
            lemonToast.error('No reviews to copy!')
            return
        }
        const rows = getReviewClipboardRows(reviews)
        const payload =
            format === 'json'
                ? JSON.stringify(rows, null, 4)
                : Papa.unparse(rows, format === 'tsv' ? { delimiter: '\t' } : undefined)
        void copyToClipboard(payload, 'reviews')
    } catch {
        lemonToast.error('Copy failed!')
    }
}
