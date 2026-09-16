import type React from 'react'

import { VariationCell } from 'scenes/web-analytics/tiles/WebAnalyticsTile'

/** What every web analytics query returns per metric: this period and the one before it. */
export type ComparedValue = [number, number | null]

export interface BreakdownTableColumn<Row> {
    key: string
    title: string
    /** Shown instead of `title` once the table is too narrow to spell it out. */
    shortTitle?: string
    tooltip?: string
    value: (row: Row) => ComparedValue | null
    /** Built once at module level: VariationCell is a factory, and calling it in render would make
     * a new component type on every pass. */
    Cell: ReturnType<typeof VariationCell>
    exportLabel: string
    exportValue?: (value: number) => string
    tooltipContent?: (row: Row) => React.ReactNode
}

/** Sorts on the current period. A row with no value sorts last in either direction. */
export const compareByCurrent =
    <Row>(column: BreakdownTableColumn<Row>) =>
    (a: Row, b: Row): number =>
        (column.value(a)?.[0] ?? -Infinity) - (column.value(b)?.[0] ?? -Infinity)
