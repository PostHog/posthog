import { WebStatsTableQueryResponse } from '~/queries/schema/schema-general'

import type { ComparedValue } from './breakdownTableColumn'

export interface WebStatsRow {
    breakdownValue: string
    visitors?: ComparedValue
    sessions?: ComparedValue
    views?: ComparedValue
    bounce_rate?: ComparedValue
    session_duration?: ComparedValue
    total_conversions?: ComparedValue
    unique_conversions?: ComparedValue
    conversion_rate?: ComparedValue
}

const COLUMN_PREFIX = 'context.columns.'

/** Presentation columns the backend appends for the query table's own chrome. */
const IGNORED_COLUMNS = new Set(['ui_fill_fraction', 'cross_sell'])

const toCompared = (value: unknown): ComparedValue | undefined => {
    if (Array.isArray(value)) {
        const [current, previous] = value
        return typeof current === 'number' ? [current, typeof previous === 'number' ? previous : null] : undefined
    }
    return typeof value === 'number' ? [value, null] : undefined
}

/** Zips the response's parallel columns and rows into one object per breakdown value. */
export function webStatsRows(response: WebStatsTableQueryResponse | undefined): WebStatsRow[] {
    const columns = (response?.columns ?? []) as string[]
    const results = (response?.results ?? []) as unknown[][]

    return results.map((row) => {
        const parsed: WebStatsRow = { breakdownValue: '' }
        columns.forEach((column, index) => {
            const name = column.startsWith(COLUMN_PREFIX) ? column.slice(COLUMN_PREFIX.length) : column
            if (IGNORED_COLUMNS.has(name)) {
                return
            }
            if (name === 'breakdown_value') {
                parsed.breakdownValue = String(row[index] ?? '')
                return
            }
            const compared = toCompared(row[index])
            if (compared) {
                ;(parsed as unknown as Record<string, ComparedValue>)[name] = compared
            }
        })
        return parsed
    })
}
