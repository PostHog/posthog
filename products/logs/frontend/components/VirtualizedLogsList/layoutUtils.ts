import type { CSSProperties } from 'react'

import { VirtualizedTableColumn } from 'products/logs/frontend/components/VirtualizedLogsList/types'

// Layout constants for log rows
export const DEFAULT_ATTRIBUTE_COLUMN_WIDTH = 150
export const MIN_ATTRIBUTE_COLUMN_WIDTH = 80
export const RESIZER_HANDLE_WIDTH = 16

// Fixed column widths
export const SEVERITY_WIDTH = 8
export const CHECKBOX_WIDTH = 28
export const EXPAND_WIDTH = 28
export const TIMESTAMP_WIDTH = 180
export const MESSAGE_MIN_WIDTH = 300
export const LOG_ROW_FAB_WIDTH = 150
export const ROW_GAP = 8
export const LOG_ROW_HEADER_HEIGHT = 32

const FIXED_COLUMNS_TOTAL_WIDTH = SEVERITY_WIDTH + CHECKBOX_WIDTH + EXPAND_WIDTH + TIMESTAMP_WIDTH

export const getAttributeColumnWidth = (attributeKey: string, attributeColumnWidths: Record<string, number>): number =>
    attributeColumnWidths[attributeKey] ?? DEFAULT_ATTRIBUTE_COLUMN_WIDTH

export const getFixedColumnsWidth = (
    attributeColumns: string[] = [],
    attributeColumnWidths: Record<string, number> = {}
): number => {
    const attrWidths = attributeColumns.reduce(
        (sum, key) => sum + getAttributeColumnWidth(key, attributeColumnWidths),
        0
    )
    const gaps = (3 + attributeColumns.length) * ROW_GAP
    return FIXED_COLUMNS_TOTAL_WIDTH + attrWidths + gaps
}

export const getMinRowWidth = (
    attributeColumns: string[] = [],
    attributeColumnWidths: Record<string, number> = {}
): number => getFixedColumnsWidth(attributeColumns, attributeColumnWidths) + MESSAGE_MIN_WIDTH

export const getMessageStyle = (flexWidth?: number): CSSProperties => ({
    flexGrow: 1,
    flexShrink: 1,
    flexBasis: flexWidth ? Math.max(flexWidth, MESSAGE_MIN_WIDTH) : MESSAGE_MIN_WIDTH,
    minWidth: MESSAGE_MIN_WIDTH,
})

// Column-aware layout helpers (used with VirtualizedTableColumn)

/** Sum column widths. When includeFlex is false, flex columns contribute 0. */
function sumColumnWidths<T extends Record<string, any>>(
    columns: VirtualizedTableColumn<T>[],
    includeFlex: boolean
): number {
    let totalWidth = 0
    let resizerCount = 0
    let gapCount = 0

    for (const col of columns) {
        if (col.isHidden) {
            continue
        }
        switch (col.sizing.type) {
            case 'fixed':
                totalWidth += col.sizing.width
                gapCount++
                break
            case 'resizable':
                totalWidth += col.sizing.width
                resizerCount++
                gapCount++
                break
            case 'flex':
                if (includeFlex) {
                    totalWidth += col.sizing.minWidth
                }
                gapCount++
                break
        }
    }

    const gaps = Math.max(0, gapCount - 1) * ROW_GAP
    return totalWidth + resizerCount * RESIZER_HANDLE_WIDTH + gaps
}

/** Total width of all non-flex columns including gaps and resizer handles */
export function getColumnsFixedWidth<T extends Record<string, any>>(columns: VirtualizedTableColumn<T>[]): number {
    return sumColumnWidths(columns, false)
}

/** Minimum row width (flex columns contribute their minWidth) */
export function getColumnsMinRowWidth<T extends Record<string, any>>(columns: VirtualizedTableColumn<T>[]): number {
    return sumColumnWidths(columns, true)
}
