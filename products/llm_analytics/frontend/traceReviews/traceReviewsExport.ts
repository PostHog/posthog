import Papa from 'papaparse'

import { traceReviewListParamsFromFilters, traceReviewsApi, type TraceReviewListFilters } from './traceReviewsApi'
import type { TraceReview } from './types'

export type ReviewClipboardFormat = 'csv' | 'json' | 'tsv'

export const CLIPBOARD_ROW_LIMIT = 5000
const CLIPBOARD_PAGE_SIZE = 500
const LEVEL_SEP = '.'

// Mirrors rest_framework_csv.CSVRenderer.flatten_item so client-side clipboard
// output matches the server-side file export shape exactly: nested dicts produce
// dotted keys (created_by.email), and lists expand by index (scores.0.id, scores.1.id).
function nestFlatItem(flat: Record<string, unknown>, prefix: string): Record<string, unknown> {
    const nested: Record<string, unknown> = {}
    for (const [header, val] of Object.entries(flat)) {
        nested[header ? `${prefix}${LEVEL_SEP}${header}` : prefix] = val
    }
    return nested
}

function flattenItem(item: unknown): Record<string, unknown> {
    if (Array.isArray(item)) {
        const flat: Record<string, unknown> = {}
        item.forEach((value, index) => {
            Object.assign(flat, nestFlatItem(flattenItem(value), String(index)))
        })
        return flat
    }
    if (item !== null && typeof item === 'object') {
        const flat: Record<string, unknown> = {}
        for (const [key, value] of Object.entries(item as Record<string, unknown>)) {
            Object.assign(flat, nestFlatItem(flattenItem(value), key))
        }
        return flat
    }
    return { '': item }
}

export function getReviewClipboardRows(reviews: TraceReview[]): Record<string, unknown>[] {
    return reviews.map((review) => flattenItem(review))
}

export async function fetchAllReviewsForExport(
    filters: TraceReviewListFilters,
    maxRows: number = CLIPBOARD_ROW_LIMIT
): Promise<{ reviews: TraceReview[]; total: number; truncated: boolean }> {
    const baseParams = traceReviewListParamsFromFilters(filters)

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

export function formatReviewsForClipboard(reviews: TraceReview[], format: ReviewClipboardFormat): string {
    const rows = getReviewClipboardRows(reviews)
    if (format === 'json') {
        return JSON.stringify(rows, null, 4)
    }
    return Papa.unparse(rows, format === 'tsv' ? { delimiter: '\t' } : undefined)
}
