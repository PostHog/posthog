import Papa from 'papaparse'

import { lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { flattenObject } from '~/queries/nodes/DataTable/clipboardUtils'

import { traceReviewsApi } from './traceReviewsApi'
import type { TraceReview } from './types'

export type ReviewClipboardFormat = 'csv' | 'json' | 'tsv'

export interface ReviewClipboardFilters {
    search: string
    definition_id: string
    order_by: string
}

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

export const CLIPBOARD_ROW_LIMIT = 5000
const CLIPBOARD_PAGE_SIZE = 500

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

export async function fetchAllReviewsForExport(
    filters: ReviewClipboardFilters,
    maxRows: number = CLIPBOARD_ROW_LIMIT
): Promise<{ reviews: TraceReview[]; total: number; truncated: boolean }> {
    const baseParams = {
        search: filters.search || undefined,
        definition_id: filters.definition_id || undefined,
        order_by: filters.order_by,
    }

    const first = await traceReviewsApi.list({
        ...baseParams,
        offset: 0,
        limit: CLIPBOARD_PAGE_SIZE,
    })

    if (first.count > maxRows) {
        return { reviews: first.results, total: first.count, truncated: true }
    }

    const reviews = [...first.results]
    while (reviews.length < first.count) {
        const page = await traceReviewsApi.list({
            ...baseParams,
            offset: reviews.length,
            limit: CLIPBOARD_PAGE_SIZE,
        })
        if (page.results.length === 0) {
            break
        }
        reviews.push(...page.results)
    }

    return { reviews, total: first.count, truncated: false }
}

export async function copyReviewsAs(filters: ReviewClipboardFilters, format: ReviewClipboardFormat): Promise<void> {
    try {
        const { reviews, total, truncated } = await fetchAllReviewsForExport(filters)

        if (total === 0) {
            lemonToast.error('No reviews to copy!')
            return
        }

        if (truncated) {
            lemonToast.warning(
                `Too many reviews to copy to clipboard (${total}). Use "Export current columns" to download a file instead.`
            )
            return
        }

        const rows = getReviewClipboardRows(reviews)
        const payload =
            format === 'json'
                ? JSON.stringify(rows, null, 4)
                : Papa.unparse(rows, format === 'tsv' ? { delimiter: '\t' } : undefined)
        await copyToClipboard(payload, 'reviews')
    } catch {
        lemonToast.error('Copy failed!')
    }
}
