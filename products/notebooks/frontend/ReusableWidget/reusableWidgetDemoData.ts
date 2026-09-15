import type { WidgetFrameApi } from '../generated/api.schemas'

export function demoRowsAsJSON(frame: WidgetFrameApi): string {
    return JSON.stringify(
        frame.rows.map((row) => Object.fromEntries(frame.columns.map((column, index) => [column.name, row[index]]))),
        null,
        2
    )
}

export function parseDemoRows(text: string, columns: WidgetFrameApi['columns']): WidgetFrameApi['rows'] {
    let parsed: unknown
    try {
        parsed = JSON.parse(text)
    } catch {
        throw new Error('Enter valid JSON: an array of row objects.')
    }
    if (!Array.isArray(parsed)) {
        throw new Error('Enter an array of row objects.')
    }
    if (parsed.length > 20) {
        throw new Error('Save at most 20 demo rows per input.')
    }
    return parsed.map((row: unknown, index) => {
        if (!row || typeof row !== 'object' || Array.isArray(row)) {
            throw new Error(`Row ${index + 1} must be an object with a value for every column.`)
        }
        const values = row as Record<string, unknown>
        if (
            Object.keys(values).length !== columns.length ||
            columns.some((column) => !Object.prototype.hasOwnProperty.call(values, column.name))
        ) {
            throw new Error(
                `Row ${index + 1} must contain exactly these columns: ${columns.map((c) => c.name).join(', ')}.`
            )
        }
        return columns.map((column) => values[column.name])
    })
}
