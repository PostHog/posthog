import { AggregatedSpanRow } from '~/queries/schema/schema-general'

// Shared with TraceCompareFlame's node coloring so the table's Regressed/Improved buckets and
// the flame's red/green bars agree on what counts as a change: ±20% on the row's p95 (the
// flame colors per-node on p50, same threshold).
export const CHANGE_THRESHOLD = 0.2

// Rows with fewer baseline samples than this classify as unchanged — percentage deltas on a
// handful of spans are noise, and they'd otherwise dominate the change-first sort.
export const MIN_BASELINE_COUNT = 10

export type CompareRowStatus = 'regressed' | 'improved' | 'new' | 'gone' | 'unchanged'

export interface CompareRow {
    service_name: string
    name: string
    current: AggregatedSpanRow | null
    previous: AggregatedSpanRow | null
}

export const compareRowKey = (row: { service_name: string; name: string }): string => `${row.service_name} ${row.name}`

export function buildRows(current: AggregatedSpanRow[], previous: AggregatedSpanRow[] | null): CompareRow[] {
    const previousByKey = new Map<string, AggregatedSpanRow>()
    for (const row of previous ?? []) {
        previousByKey.set(compareRowKey(row), row)
    }

    const rows: CompareRow[] = current.map((row) => ({
        service_name: row.service_name,
        name: row.name,
        current: row,
        previous: previousByKey.get(compareRowKey(row)) ?? null,
    }))

    // Append rows that existed in the previous window but disappeared in the current window —
    // useful for spotting fully regressed call sites.
    const currentKeys = new Set(current.map(compareRowKey))
    for (const row of previous ?? []) {
        const key = compareRowKey(row)
        if (!currentKeys.has(key)) {
            rows.push({
                service_name: row.service_name,
                name: row.name,
                current: null,
                previous: row,
            })
        }
    }

    return rows
}

/** Relative change (0.5 = +50%), or null when there's no meaningful baseline. */
export function relativeDelta(current: number | null | undefined, previous: number | null | undefined): number | null {
    if (current === null || current === undefined || previous === null || previous === undefined || previous === 0) {
        return null
    }
    return (current - previous) / previous
}

/** The row's p95 relative delta with the min-baseline-count noise guard applied. */
function guardedP95Delta(row: CompareRow): number | null {
    if (!row.current || !row.previous || row.previous.count < MIN_BASELINE_COUNT) {
        return null
    }
    return relativeDelta(row.current.p95_duration_nano, row.previous.p95_duration_nano)
}

export function classifyRow(row: CompareRow): CompareRowStatus {
    if (!row.current) {
        return 'gone'
    }
    if (!row.previous) {
        return 'new'
    }
    const delta = guardedP95Delta(row)
    if (delta === null) {
        return 'unchanged'
    }
    if (delta > CHANGE_THRESHOLD) {
        return 'regressed'
    }
    if (delta < -CHANGE_THRESHOLD) {
        return 'improved'
    }
    return 'unchanged'
}

/**
 * Sort key for the default change-first ordering: biggest movers (either direction) first.
 * New rows are by definition maximal change; gone rows sort below everything, including
 * unchanged rows, so vanished call sites collect at the bottom under a descending sort.
 */
export function changeMagnitude(row: CompareRow): number {
    if (!row.current) {
        return -1
    }
    if (!row.previous) {
        return Number.MAX_VALUE
    }
    return Math.abs(guardedP95Delta(row) ?? 0)
}
