import { formatMonthDay } from '@/lib/dates'
import { formatInsightValue } from '@/model/adapters/insightFormatting'
import { sqlCellNumber } from '@/model/adapters/sqlVisualization'
import { groupThousands, plural } from '@/model/adapters/text'
import type { InsightPresentation, SqlCell, SqlColumnView, SqlTableView } from '@/model/views'

const DATE_PARTS = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/
const INTEGER_TEXT = /^\s*-?\d+\s*$/
const RAW: InsightPresentation = { kind: 'sql', style: null, prefix: '', suffix: '' }

/**
 * A number cell through the same formatter as the chart and the big number. An integer string past 2^53 has no exact
 * JS number, so without a style or decimals it keeps its digits as the server wrote them.
 */
function formatNumber(cell: SqlCell, value: number, presentation: InsightPresentation | null): string {
    const format = presentation ?? RAW
    const raw = (format.style === null || format.style === 'none') && format.decimalPlaces === undefined
    if (raw && typeof cell === 'string' && INTEGER_TEXT.test(cell) && !Number.isSafeInteger(value)) {
        return `${format.prefix}${cell.trim()}${format.suffix}`
    }
    return formatInsightValue(value, { valueFormat: 'number', unit: null, presentation: format })
}

/**
 * "Oct 3", or "Oct 3, 2025" outside the current year. A DATETIME adds "14:05". The server writes the project's wall
 * clock into the string, so the digits are read as written and not converted to the device's time zone.
 */
function formatDate(text: string, withTime: boolean, now: number): string {
    const match = DATE_PARTS.exec(text)
    if (!match) {
        return text
    }
    const [, year, month, day, hours, minutes] = match
    const date = new Date(Number(year), Number(month) - 1, Number(day))
    const dayText =
        date.getFullYear() === new Date(now).getFullYear()
            ? formatMonthDay(date)
            : `${formatMonthDay(date)}, ${date.getFullYear()}`
    return withTime && hours !== undefined && minutes !== undefined ? `${dayText}, ${hours}:${minutes}` : dayText
}

export function formatSqlCell(cell: SqlCell, column: SqlColumnView, now: number = Date.now()): string | null {
    if (cell === null) {
        return null
    }
    if (typeof cell === 'boolean') {
        return cell ? 'true' : 'false'
    }
    if (column.scalar === 'BOOLEAN' && typeof cell === 'number') {
        return cell === 0 ? 'false' : 'true'
    }
    if (column.isNumerical) {
        const value = sqlCellNumber(cell)
        return value === undefined ? String(cell) : formatNumber(cell, value, column.format)
    }
    if (column.isDate && typeof cell === 'string') {
        return formatDate(cell, column.scalar === 'DATETIME', now)
    }
    return String(cell)
}

/**
 * Without a row limit the table draws at most this many rows, so a query with a large LIMIT cannot stall a screen. The
 * rows are plain views, not a virtual list, and 1,000 of them blocked the web build's JS thread for over 200 ms.
 */
export const SQL_TABLE_MAX_ROWS = 500

/**
 * "8 rows", or "First 100 rows" when the server cut the result. With `drawn` below the row count, as when a screen
 * draws `SQL_TABLE_MAX_ROWS`, it says so: "First 500 of 5,000 rows", or "of 5,000+" when the server cut it too.
 */
export function sqlRowsText(table: Pick<SqlTableView, 'rows' | 'hasMore'>, drawn: number = table.rows.length): string {
    const count = table.rows.length
    if (drawn < count) {
        return `First ${groupThousands(drawn)} of ${groupThousands(count)}${table.hasMore ? '+' : ''} rows`
    }
    const rows = plural(count, 'row')
    return table.hasMore ? `First ${rows}` : rows
}
