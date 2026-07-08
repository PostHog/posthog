export interface InsightActorsData {
    query: Record<string, unknown>
    results: {
        columns: string[]
        results: (string | number | null | string[])[][]
    }
    hasMore: boolean
    offset: number
    _posthogUrl?: string
}

export interface ActorRow {
    distinct_id: string | null
    email: string | null
    name: string | null
    event_count: number | null
    recordings: string[]
}

function rowToObject(columns: string[], row: (string | number | null | string[])[]): Record<string, unknown> {
    const obj: Record<string, unknown> = {}
    columns.forEach((col, i) => {
        obj[col] = row[i]
    })
    return obj
}

export function toActorRows(data: InsightActorsData): ActorRow[] {
    const { columns, results } = data.results
    return results.map((row) => {
        const obj = rowToObject(columns, row)
        return {
            distinct_id: (obj.distinct_id as string) ?? null,
            email: (obj.email as string) ?? null,
            name: (obj.name as string) ?? null,
            event_count: (obj.event_count as number) ?? null,
            recordings: Array.isArray(obj.recordings) ? (obj.recordings as string[]) : [],
        }
    })
}

// Retention actors project one `<period>_N` column per return interval (e.g. `day_0`, `week_1`),
// each cell 1/0 — a fundamentally different shape from the event-count actor table.
const RETENTION_COLUMN_RE = /^(day|week|month|hour)_(\d+)$/

export function isRetentionActorsData(data: InsightActorsData): boolean {
    return data.results.columns.some((col) => RETENTION_COLUMN_RE.test(col))
}

export interface RetentionPeriodColumn {
    interval: number
    label: string
    index: number
}

/** The `<period>_N` columns, ordered by interval, with display labels (`Day 0`, `Week 1`, …). */
export function retentionPeriodColumns(data: InsightActorsData): RetentionPeriodColumn[] {
    const cols: RetentionPeriodColumn[] = []
    data.results.columns.forEach((name, index) => {
        const match = RETENTION_COLUMN_RE.exec(name)
        if (match) {
            const period = match[1] ?? 'day'
            const interval = Number(match[2])
            cols.push({ interval, label: `${period.charAt(0).toUpperCase()}${period.slice(1)} ${interval}`, index })
        }
    })
    return cols.sort((a, b) => a.interval - b.interval)
}

export interface RetentionActorRow {
    distinct_id: string | null
    email: string | null
    name: string | null
    /** Whether the actor returned in each interval, aligned to `retentionPeriodColumns` order. */
    appearances: boolean[]
}

export function toRetentionActorRows(
    data: InsightActorsData,
    periodCols: RetentionPeriodColumn[]
): RetentionActorRow[] {
    const { columns, results } = data.results
    return results.map((row) => {
        const obj = rowToObject(columns, row)
        return {
            distinct_id: (obj.distinct_id as string) ?? null,
            email: (obj.email as string) ?? null,
            name: (obj.name as string) ?? null,
            appearances: periodCols.map((pc) => !!row[pc.index]),
        }
    })
}

export interface RetentionIntervalSummary extends RetentionPeriodColumn {
    count: number
    percentage: number
}

// Per-interval retained count + percentage for the column headers, computed over the returned rows.
// Percentage is relative to interval 0 (the cohort baseline), matching the app's persons-modal header.
export function summarizeRetentionIntervals(
    rows: RetentionActorRow[],
    periodCols: RetentionPeriodColumn[]
): RetentionIntervalSummary[] {
    const countAt = (i: number): number => rows.reduce((acc, row) => acc + (row.appearances[i] ? 1 : 0), 0)
    const baseCount = periodCols.length > 0 ? countAt(0) : 0
    return periodCols.map((pc, i) => {
        const count = countAt(i)
        const percentage = baseCount > 0 ? Math.round((count / baseCount) * 10000) / 100 : 0
        return { ...pc, count, percentage }
    })
}
