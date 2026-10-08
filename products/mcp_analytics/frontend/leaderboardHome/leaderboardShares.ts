import { normalizeBucket } from 'lib/utils/timeBuckets'

import { type HarnessRow, type ToolRow } from '../mcpDashboardOverviewLogic'

export type ModelLab = 'Anthropic' | 'OpenAI' | 'Google' | 'xAI' | 'Cursor' | 'Open weights' | 'Other'

export interface BucketedFacetRow {
    bucket: string
    label: string
    calls: number
}

export interface WindowFacetRow {
    label: string
    calls: number
    // null for a folded "Other" row: distinct users cannot be summed across labels.
    users: number | null
    errors: number
}

export interface ShareSeries {
    label: string
    data: number[]
}

export interface LabShare {
    lab: ModelLab
    share: number
}

export interface LabUsersRow {
    lab: string
    users: number
}

export type ScoreboardMetric = 'calls' | 'users'

export interface ReliabilityRow {
    bucket: string
    calls: number
    errors: number
    p50: number
    p95: number
}

export interface ReliabilitySeries {
    labels: string[]
    errorRatePct: number[]
    p50: number[]
    p95: number[]
}

const UNKNOWN = 'Unknown'
const OTHER = 'Other'

// The first matching pattern wins. The SQL for the users query is built from the same list, so the
// two cannot disagree on which lab a model belongs to.
const LAB_PATTERNS: [Exclude<ModelLab, 'Other'>, RegExp][] = [
    [
        'Open weights',
        /gpt-oss|deepseek|glm|kimi|qwen|llama|mistral|minimax|gemma|nemotron|olmo|devstral|codestral|mimo|^phi/,
    ],
    ['Anthropic', /claude|opus|sonnet|haiku|fable|anthropic/],
    ['OpenAI', /gpt|^o[1-9]|codex|openai|chatgpt/],
    ['Google', /gemini|google/],
    ['xAI', /grok|xai/],
    ['Cursor', /composer/],
]

export function modelLab(model: string): ModelLab {
    const m = model.toLowerCase()
    return LAB_PATTERNS.find(([, pattern]) => pattern.test(m))?.[0] ?? 'Other'
}

export function labSqlExpression(modelSql: string): string {
    const branches = LAB_PATTERNS.map(([lab, pattern]) => `match(lower(${modelSql}), '${pattern.source}'), '${lab}'`)
    return `multiIf(${modelSql} = '${UNKNOWN}', '${UNKNOWN}', ${branches.join(', ')}, 'Other')`
}

// `groupOf` returns null to drop a row. The top `limit` groups by total calls keep their own series
// and the rest fold into one "Other" series, which is always last.
export function buildShareSeries(
    rows: BucketedFacetRow[],
    bucketKeys: string[],
    groupOf: (label: string) => string | null,
    limit: number
): ShareSeries[] {
    const bucketIndex = new Map(bucketKeys.map((key, index) => [key, index]))
    const byGroup = new Map<string, number[]>()
    for (const row of rows) {
        const group = groupOf(row.label)
        const index = bucketIndex.get(row.bucket)
        if (group === null || index === undefined) {
            continue
        }
        const data = byGroup.get(group) ?? bucketKeys.map(() => 0)
        data[index] += row.calls
        byGroup.set(group, data)
    }
    const total = (data: number[]): number => data.reduce((sum, value) => sum + value, 0)
    const ranked = [...byGroup.entries()]
        .filter(([group]) => group !== OTHER)
        .sort(([, a], [, b]) => total(b) - total(a))
    const series: ShareSeries[] = ranked.slice(0, limit).map(([label, data]) => ({ label, data }))
    const folded = [
        ...ranked.slice(limit).map(([, data]) => data),
        ...(byGroup.has(OTHER) ? [byGroup.get(OTHER)!] : []),
    ]
    if (folded.length > 0) {
        series.push({
            label: OTHER,
            data: bucketKeys.map((_, index) => folded.reduce((sum, data) => sum + data[index], 0)),
        })
    }
    return series
}

// Shares are of calls from models that name themselves, so a lab's share is not diluted by "Unknown".
export function buildLabShares(rows: BucketedFacetRow[]): LabShare[] {
    const callsByLab = new Map<ModelLab, number>()
    for (const row of rows) {
        if (row.label !== UNKNOWN) {
            const lab = modelLab(row.label)
            callsByLab.set(lab, (callsByLab.get(lab) ?? 0) + row.calls)
        }
    }
    const total = [...callsByLab.values()].reduce((sum, calls) => sum + calls, 0)
    return [...callsByLab.entries()]
        .filter(([lab]) => lab !== 'Other')
        .sort(([, a], [, b]) => b - a)
        .map(([lab, calls]) => ({ lab, share: total > 0 ? (calls / total) * 100 : 0 }))
}

// A person can use models from several labs, so these shares do not add up to 100.
export function buildLabUserShares(rows: LabUsersRow[], namedModelUsers: number): LabShare[] {
    return rows
        .filter((row): row is { lab: ModelLab; users: number } => row.lab !== UNKNOWN && row.lab !== 'Other')
        .sort((a, b) => b.users - a.users)
        .map(({ lab, users }) => ({ lab, share: namedModelUsers > 0 ? (users / namedModelUsers) * 100 : 0 }))
}

const HARNESS_ERROR_RATE_LIMIT = 8

// The most used harnesses, so a harness with a handful of calls cannot top the error rate chart.
export function harnessErrorRateRows(rows: HarnessRow[]): ToolRow[] {
    return rows
        .filter((row) => row.category !== OTHER)
        .sort((a, b) => b.total_calls - a.total_calls)
        .slice(0, HARNESS_ERROR_RATE_LIMIT)
        .map((row) => ({
            tool: row.category,
            total_calls: row.total_calls,
            errors: row.errors,
            error_rate_pct: row.error_rate_pct,
            p95_duration_ms: 0,
        }))
}

export function hasKnownLabels(rows: WindowFacetRow[]): boolean {
    return rows.some((row) => row.label !== UNKNOWN && row.calls > 0)
}

// Biggest first, "Unknown" and "Other" last, and anything past `limit` folds into "Other".
export function topFacetRows(rows: WindowFacetRow[], limit: number): WindowFacetRow[] {
    const isNamed = (row: WindowFacetRow): boolean => row.label !== UNKNOWN && row.label !== OTHER
    const named = rows.filter(isNamed).sort((a, b) => b.calls - a.calls)
    const kept = named.slice(0, limit)
    const folded = [...named.slice(limit), ...rows.filter((row) => row.label === OTHER)]
    const result = [...kept]
    if (folded.length > 0) {
        result.push({
            label: OTHER,
            calls: folded.reduce((sum, row) => sum + row.calls, 0),
            users: null,
            errors: folded.reduce((sum, row) => sum + row.errors, 0),
        })
    }
    return [...result, ...rows.filter((row) => row.label === UNKNOWN)]
}

// A bucket with calls but no duration samples has null quantiles, which must stay gaps instead of 0.
const nullToNaN = (value: unknown): number => (value == null ? NaN : Number(value))

export const toReliabilityRows = (rows: unknown[][]): ReliabilityRow[] =>
    rows.map((r) => ({
        bucket: normalizeBucket(r[0]),
        calls: Number(r[1]),
        errors: Number(r[2]),
        p50: nullToNaN(r[3]),
        p95: nullToNaN(r[4]),
    }))

// A bucket with no calls has no row, so it becomes a NaN gap that the line charts skip.
export function buildReliabilitySeries(rows: ReliabilityRow[], bucketKeys: string[]): ReliabilitySeries {
    const byBucket = new Map(rows.map((row) => [row.bucket, row]))
    const valueFor = (key: string, valueOf: (row: ReliabilityRow) => number): number => {
        const row = byBucket.get(key)
        return row ? valueOf(row) : NaN
    }
    return {
        labels: bucketKeys,
        errorRatePct: bucketKeys.map((key) => valueFor(key, (row) => (row.errors / row.calls) * 100)),
        p50: bucketKeys.map((key) => valueFor(key, (row) => row.p50)),
        p95: bucketKeys.map((key) => valueFor(key, (row) => row.p95)),
    }
}
