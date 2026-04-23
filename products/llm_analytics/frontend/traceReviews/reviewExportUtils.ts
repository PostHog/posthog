import Papa from 'papaparse'

import { lemonToast } from '@posthog/lemon-ui'

import { TriggerExportProps } from 'lib/components/ExportButton/exporter'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { addProjectIdIfMissing } from 'lib/utils/router-utils'
import { urls } from 'scenes/urls'

import { ExporterFormat } from '~/types'

import { traceReviewsApi } from './traceReviewsApi'
import type { TraceReview, TraceReviewListParams, TraceReviewScore } from './types'
import { formatNumericTraceReviewScore, getTraceReviewScoreDisplayValue, getTraceReviewScores } from './utils'

export const REVIEW_EXPORT_MAX_ROWS = 10000
export const REVIEW_EXPORT_PAGE_SIZE = 500

const CORE_COLUMNS = [
    'Trace ID',
    'Trace URL',
    'Comment',
    'Reviewer name',
    'Reviewer email',
    'Scores',
    'Created at',
    'Updated at',
] as const

export function getTraceAbsoluteUrl(traceId: string, origin: string = window.location.origin): string {
    return `${origin}${addProjectIdIfMissing(urls.llmAnalyticsTrace(traceId))}`
}

function formatScoreValue(score: TraceReviewScore): string {
    if (score.definition_kind === 'numeric') {
        return formatNumericTraceReviewScore(score.numeric_value)
    }

    return getTraceReviewScoreDisplayValue(score)
}

export function formatScoresSummary(review: TraceReview): string {
    const scores = getTraceReviewScores(review)

    if (scores.length === 0) {
        return ''
    }

    return scores.map((score) => `${score.definition_name}: ${formatScoreValue(score)}`).join('; ')
}

export function getReviewerName(review: TraceReview): string {
    const reviewer = review.reviewed_by

    if (!reviewer) {
        return ''
    }

    const parts = [reviewer.first_name, reviewer.last_name].filter((part) => !!part && String(part).length > 0)

    if (parts.length > 0) {
        return parts.join(' ')
    }

    return reviewer.email || reviewer.distinct_id || ''
}

export function getReviewerEmail(review: TraceReview): string {
    return review.reviewed_by?.email || ''
}

function collectScoreDefinitionNames(reviews: TraceReview[]): string[] {
    const seen = new Map<string, string>()

    for (const review of reviews) {
        for (const score of getTraceReviewScores(review)) {
            if (!seen.has(score.definition_id)) {
                seen.set(score.definition_id, score.definition_name)
            }
        }
    }

    return Array.from(seen.values()).sort((a, b) => a.localeCompare(b))
}

export function buildReviewExportTableData(reviews: TraceReview[], origin?: string): string[][] {
    const scoreDefinitionNames = collectScoreDefinitionNames(reviews)
    const perScoreHeaders = scoreDefinitionNames.map((name) => `Score: ${name}`)
    const headers = [...CORE_COLUMNS, ...perScoreHeaders]

    const rows = reviews.map((review) => {
        const scoresByName = new Map<string, string>()
        for (const score of getTraceReviewScores(review)) {
            scoresByName.set(score.definition_name, formatScoreValue(score))
        }

        const coreValues: string[] = [
            review.trace_id ?? '',
            review.trace_id ? getTraceAbsoluteUrl(review.trace_id, origin) : '',
            review.comment ?? '',
            getReviewerName(review),
            getReviewerEmail(review),
            formatScoresSummary(review),
            review.created_at ?? '',
            review.updated_at ?? '',
        ]

        return [...coreValues, ...scoreDefinitionNames.map((name) => scoresByName.get(name) ?? '')]
    })

    return [headers, ...rows]
}

export function buildReviewExportJsonData(reviews: TraceReview[], origin?: string): Record<string, unknown>[] {
    return reviews.map((review) => {
        const scoresByName: Record<string, string> = {}
        for (const score of getTraceReviewScores(review)) {
            scoresByName[score.definition_name] = formatScoreValue(score)
        }

        return {
            trace_id: review.trace_id,
            trace_url: review.trace_id ? getTraceAbsoluteUrl(review.trace_id, origin) : '',
            comment: review.comment,
            reviewer_name: getReviewerName(review) || null,
            reviewer_email: getReviewerEmail(review) || null,
            scores: scoresByName,
            created_at: review.created_at,
            updated_at: review.updated_at,
        }
    })
}

export async function fetchAllReviewsForExport(
    filters: Omit<TraceReviewListParams, 'offset' | 'limit'>,
    options?: { maxRows?: number; pageSize?: number }
): Promise<{ reviews: TraceReview[]; truncated: boolean; total: number | undefined }> {
    const maxRows = options?.maxRows ?? REVIEW_EXPORT_MAX_ROWS
    const pageSize = Math.min(options?.pageSize ?? REVIEW_EXPORT_PAGE_SIZE, maxRows)

    const all: TraceReview[] = []
    let offset = 0
    let total: number | undefined

    while (all.length < maxRows) {
        const response = await traceReviewsApi.list({ ...filters, offset, limit: pageSize })
        total = response.count

        all.push(...response.results)

        if (response.results.length < pageSize) {
            break
        }

        if (typeof response.count === 'number' && all.length >= response.count) {
            break
        }

        offset += pageSize
    }

    const truncated = all.length >= maxRows && typeof total === 'number' && total > maxRows
    return { reviews: all.slice(0, maxRows), truncated, total }
}

export function exportTimestampFilename(prefix: string, extension: string): string {
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    return `${prefix}-${stamp}.${extension}`
}

function triggerLocalExport(
    exportCall: (exportData: TriggerExportProps) => void,
    localData: string,
    filename: string,
    mediaType: ExporterFormat
): void {
    exportCall({
        export_format: mediaType,
        export_context: {
            localData,
            filename,
            mediaType,
        },
    })
}

export function downloadReviewsAsCsv(
    reviews: TraceReview[],
    exportCall: (exportData: TriggerExportProps) => void
): void {
    const tableData = buildReviewExportTableData(reviews)
    const csv = Papa.unparse(tableData)
    triggerLocalExport(exportCall, csv, exportTimestampFilename('llm-analytics-reviews', 'csv'), ExporterFormat.CSV)
}

export function copyReviewsToCsv(reviews: TraceReview[]): void {
    try {
        const csv = Papa.unparse(buildReviewExportTableData(reviews))
        void copyToClipboard(csv, 'reviews')
    } catch {
        lemonToast.error('Copy failed!')
    }
}

export function copyReviewsToJson(reviews: TraceReview[]): void {
    try {
        const json = JSON.stringify(buildReviewExportJsonData(reviews), null, 4)
        void copyToClipboard(json, 'reviews')
    } catch {
        lemonToast.error('Copy failed!')
    }
}

export function copyReviewsToExcel(reviews: TraceReview[]): void {
    try {
        const tsv = Papa.unparse(buildReviewExportTableData(reviews), { delimiter: '\t' })
        void copyToClipboard(tsv, 'reviews')
    } catch {
        lemonToast.error('Copy failed!')
    }
}
