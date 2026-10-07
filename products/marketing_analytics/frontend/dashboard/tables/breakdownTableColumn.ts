import type React from 'react'

import type { ChangeFormat } from './formatComparedValue'

/** What every web analytics query returns per metric: this period and the one before it. */
export type ComparedValue = [number, number | null]

export interface BreakdownTableColumn<Row> {
    key: string
    title: string
    /** Shown instead of `title` once the table is too narrow to spell it out. */
    shortTitle?: string
    tooltip?: string
    value: (row: Row) => ComparedValue | null
    kind?: ChangeFormat
    /** Up is bad, as for bounce rate. */
    reverseColors?: boolean
    /** Neither direction is good or bad, so the change stays grey. */
    neutral?: boolean
    exportLabel: string
    exportValue?: (value: number) => string
    tooltipContent?: (row: Row) => React.ReactNode
}

export function compareByCurrent<Row>(
    column: BreakdownTableColumn<Row>,
    sortOrder: 1 | -1
): (a: Row, b: Row) => number {
    return (a: Row, b: Row): number => {
        const aValue = column.value(a)?.[0]
        const bValue = column.value(b)?.[0]
        if (aValue === bValue) {
            return 0
        }
        // LemonTable multiplies this result by the sort order, so compensate to keep missing values last.
        if (aValue === undefined) {
            return sortOrder
        }
        if (bValue === undefined) {
            return -sortOrder
        }
        return aValue - bValue
    }
}
