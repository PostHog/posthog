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
    status: CompareRowStatus
}

// NUL separator, not a space: span names routinely contain spaces, so a printable separator
// would let ("web api", "x") and ("web", "api x") collide on one key.
export const compareRowKey = (row: { service_name: string; name: string }): string => `${row.service_name}\0${row.name}`

export function buildRows(current: AggregatedSpanRow[], previous: AggregatedSpanRow[] | null): CompareRow[] {
    const previousByKey = new Map<string, AggregatedSpanRow>()
    for (const row of previous ?? []) {
        previousByKey.set(compareRowKey(row), row)
    }

    // A null `previous` means there is no baseline dataset at all (e.g. the compare fetch is
    // still in flight) — that must not classify every row as 'new'.
    const hasBaseline = previous !== null
    const makeRow = (
        base: { service_name: string; name: string },
        currentRow: AggregatedSpanRow | null,
        previousRow: AggregatedSpanRow | null
    ): CompareRow => ({
        service_name: base.service_name,
        name: base.name,
        current: currentRow,
        previous: previousRow,
        status: hasBaseline ? classifyRow({ current: currentRow, previous: previousRow }) : 'unchanged',
    })

    const rows: CompareRow[] = current.map((row) => makeRow(row, row, previousByKey.get(compareRowKey(row)) ?? null))

    // Append rows that existed in the previous window but disappeared in the current window —
    // useful for spotting fully regressed call sites.
    const currentKeys = new Set(current.map(compareRowKey))
    for (const row of previous ?? []) {
        if (!currentKeys.has(compareRowKey(row))) {
            rows.push(makeRow(row, null, row))
        }
    }

    return rows
}

/** Relative change (0.5 = +50%), or null when there's no meaningful baseline. */
function relativeDelta(current: number | null | undefined, previous: number | null | undefined): number | null {
    if (current === null || current === undefined || previous === null || previous === undefined || previous === 0) {
        return null
    }
    return (current - previous) / previous
}

type CompareRowSides = Pick<CompareRow, 'current' | 'previous'>

/**
 * Percentage deltas on a handful of spans are noise on either side: a row that dropped from
 * 1000 calls to 2 slow ones is not a p95 regression any more than a 2-sample baseline is.
 */
export function isLowSample(row: CompareRowSides): boolean {
    return !row.current || !row.previous || Math.min(row.current.count, row.previous.count) < MIN_BASELINE_COUNT
}

/** The row's p95 relative delta with the low-sample noise guard applied. */
function guardedP95Delta(row: CompareRowSides): number | null {
    if (!row.current || !row.previous || isLowSample(row)) {
        return null
    }
    return relativeDelta(row.current.p95_duration_nano, row.previous.p95_duration_nano)
}

export function classifyRow(row: CompareRowSides): CompareRowStatus {
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
export function changeMagnitude(row: CompareRowSides): number {
    if (!row.current) {
        return -1
    }
    if (!row.previous) {
        // Sparse new rows (unparameterized URLs and the like) would otherwise flood the top
        // of the change sort — the same noise the low-sample guard suppresses elsewhere.
        return row.current.count >= MIN_BASELINE_COUNT ? Number.MAX_VALUE : 0
    }
    return Math.abs(guardedP95Delta(row) ?? 0)
}
