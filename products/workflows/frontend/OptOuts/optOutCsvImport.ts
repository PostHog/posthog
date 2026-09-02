// Mirrors the column aliases the old server-side CSV import accepted, so a list
// exported from another messaging tool still imports without being reshaped.
export const RECIPIENT_COLUMNS = ['identifier', 'email', 'recipient', 'email_address']
export const CATEGORY_COLUMNS = ['category_key', 'category']

export const BULK_OPT_OUT_CHUNK_SIZE = 1000
export const MAX_REPORTED_ERRORS = 10

export interface ParsedOptOutEntry {
    identifier: string
    category_key?: string
    /** 1-based row number in the source file, header included, for error messages. */
    row: number
}

export interface ParsedOptOutCsv {
    entries: ParsedOptOutEntry[]
    /** Non-empty data rows in the file. */
    total: number
    skipped: number
    errors: string[]
}

// The export quote-prefixes cells starting with these so spreadsheets don't evaluate them
// as formulas (see posthog/security/spreadsheet_safety.py). Reversed here so a file
// exported from PostHog imports back with the original identifiers.
const FORMULA_TRIGGER_CHARS = ['=', '+', '-', '@', '\t', '\r']

function unescapeFormulaPrefix(value: string): string {
    return value.startsWith("'") && FORMULA_TRIGGER_CHARS.includes(value[1]) ? value.slice(1) : value
}

/** Turn parsed CSV rows (header first) into opt-out entries, mirroring the old server-side rules. */
export function parseOptOutRows(rows: string[][]): ParsedOptOutCsv {
    if (rows.length === 0) {
        return { entries: [], total: 0, skipped: 0, errors: ['The file is empty'] }
    }
    const header = rows[0].map((column) => column.trim().toLowerCase())
    const identifierIndex = RECIPIENT_COLUMNS.map((column) => header.indexOf(column)).find((index) => index >= 0)
    if (identifierIndex === undefined) {
        return {
            entries: [],
            total: 0,
            skipped: 0,
            errors: [`No recipient column found. Add a column named one of: ${RECIPIENT_COLUMNS.join(', ')}`],
        }
    }
    const categoryIndex = CATEGORY_COLUMNS.map((column) => header.indexOf(column)).find((index) => index >= 0)

    const entries: ParsedOptOutEntry[] = []
    let total = 0
    let skipped = 0
    const errors: string[] = []

    for (let i = 1; i < rows.length; i++) {
        const row = rows[i]
        if (!row.some((cell) => cell.trim())) {
            continue
        }
        total += 1
        const rowNumber = i + 1

        const identifier = unescapeFormulaPrefix(row[identifierIndex]?.trim() ?? '')
        if (!identifier) {
            skipped += 1
            if (errors.length < MAX_REPORTED_ERRORS) {
                errors.push(`Row ${rowNumber}: missing a recipient`)
            }
            continue
        }

        const categoryKey = categoryIndex !== undefined ? row[categoryIndex]?.trim() : undefined
        entries.push({ identifier, category_key: categoryKey || undefined, row: rowNumber })
    }

    return { entries, total, skipped, errors }
}

/** Rewrite the API's "Entry N" errors to name the file row the entry came from. */
export function remapEntryErrors(errors: string[], chunk: ParsedOptOutEntry[]): string[] {
    return errors.map((error) =>
        error.replace(/^Entry (\d+)/, (match, entryNumber) => {
            const entry = chunk[Number(entryNumber) - 1]
            return entry ? `Row ${entry.row}` : match
        })
    )
}
