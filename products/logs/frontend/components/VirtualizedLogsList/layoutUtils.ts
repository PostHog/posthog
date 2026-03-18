import type { CSSProperties } from 'react'

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
