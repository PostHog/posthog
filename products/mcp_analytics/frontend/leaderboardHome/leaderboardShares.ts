export type ModelLab = 'Anthropic' | 'OpenAI' | 'Google' | 'xAI' | 'Cursor' | 'Open weights' | 'Other'

export interface BucketedFacetRow {
    bucket: string
    label: string
    calls: number
}

export interface WindowFacetRow {
    label: string
    calls: number
    users: number
    errors: number
}

export interface ShareSeries {
    label: string
    data: number[]
}

export interface LabShare {
    lab: ModelLab
    calls: number
    share: number
}

const UNKNOWN = 'Unknown'
const OTHER = 'Other'

export function modelLab(model: string): ModelLab {
    const m = model.toLowerCase()
    if (
        /gpt-oss|deepseek|glm|kimi|qwen|llama|mistral|minimax|gemma|nemotron|olmo|devstral|codestral|mimo|^phi/.test(m)
    ) {
        return 'Open weights'
    }
    if (/claude|opus|sonnet|haiku|fable|anthropic/.test(m)) {
        return 'Anthropic'
    }
    if (/gpt|^o[1-9]|codex|openai|chatgpt/.test(m)) {
        return 'OpenAI'
    }
    if (/gemini|google/.test(m)) {
        return 'Google'
    }
    if (/grok|xai/.test(m)) {
        return 'xAI'
    }
    if (/composer/.test(m)) {
        return 'Cursor'
    }
    return 'Other'
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
        .map(([lab, calls]) => ({ lab, calls, share: total > 0 ? (calls / total) * 100 : 0 }))
        .sort((a, b) => b.calls - a.calls)
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
            users: folded.reduce((sum, row) => sum + row.users, 0),
            errors: folded.reduce((sum, row) => sum + row.errors, 0),
        })
    }
    return [...result, ...rows.filter((row) => row.label === UNKNOWN)]
}
