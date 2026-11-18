import { formatPercentage } from 'lib/utils/numbers'

import type { MCPToolQualityRowItem } from '~/queries/schema/schema-general'

import { formatMs } from '../dashboard/formatters'

// Below this many calls in either period, one error or one slow call swings the numbers too much.
export const MIN_CALLS_FOR_CHANGE = 20
// Starting points, not tuned: flag an error rate that moved 2 points, or a p95 that got 25% slower
// (or 20% faster, the same ratio in reverse).
const ERROR_RATE_CHANGE_POINTS = 2
const P95_SLOWER_RATIO = 1.25
// Two-proportion z-score an error rate change must also clear (about 95% confidence), so normal
// period-to-period noise on a busy tool is not flagged as a regression.
const ERROR_RATE_MIN_Z = 2

export interface QualityChange {
    worse: boolean
    label: string
    previous: string
}

type Row = Pick<
    MCPToolQualityRowItem,
    'total_calls' | 'previous_calls' | 'errors' | 'previous_errors' | 'p95_duration_ms' | 'previous_p95_duration_ms'
>

function hasEnoughCalls(row: Row): boolean {
    return Math.min(row.total_calls, row.previous_calls) >= MIN_CALLS_FOR_CHANGE
}

export function errorRateChange(row: Row): QualityChange | null {
    if (!hasEnoughCalls(row)) {
        return null
    }
    const current = row.errors / row.total_calls
    const previous = row.previous_errors / row.previous_calls
    const pooled = (row.errors + row.previous_errors) / (row.total_calls + row.previous_calls)
    const standardError = Math.sqrt(pooled * (1 - pooled) * (1 / row.total_calls + 1 / row.previous_calls))
    const diff = current - previous
    if (Math.abs(diff) * 100 < ERROR_RATE_CHANGE_POINTS || Math.abs(diff) < ERROR_RATE_MIN_Z * standardError) {
        return null
    }
    return {
        worse: diff > 0,
        label: `${Math.round(Math.abs(diff) * 1000) / 10}pp`,
        previous: formatPercentage(previous * 100, { compact: true }),
    }
}

export function p95Change(row: Row): QualityChange | null {
    const previous = row.previous_p95_duration_ms
    // A p95 of 0 means no call in that period carried a duration, not an instant tool.
    if (!hasEnoughCalls(row) || !previous || !row.p95_duration_ms) {
        return null
    }
    const ratio = row.p95_duration_ms / previous
    if (ratio < P95_SLOWER_RATIO && ratio > 1 / P95_SLOWER_RATIO) {
        return null
    }
    return { worse: ratio > 1, label: `${Math.round(Math.abs(ratio - 1) * 100)}%`, previous: formatMs(previous) }
}
