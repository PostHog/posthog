import type { AIEnrichmentRunRow } from './aiEnrichmentLogic'
import type { AIEnrichmentOutputFieldType } from './aiEnrichmentOutputFields'

export interface OutputColumnSpec {
    key: string
    type: AIEnrichmentOutputFieldType
}

// The runner's sentinel for a skipped/indeterminate verdict (enrichment/labels.py's UNKNOWN),
// written into any output key regardless of that key's declared type - most visibly a boolean
// one, where the raw string "unknown" is truthy and would otherwise render as a green success tag
// indistinguishable from a real positive. Kept only as a fallback (see isSkippedRow) - a schema
// with no boolean output field never writes this sentinel into any value at all.
export const UNKNOWN_VERDICT = 'unknown'

// The authoritative "was this row's verdict skipped" check (mirrors labels.py's
// is_unknown_output). Falls back to sniffing individual values for the literal "unknown" string
// only when `meta` is absent - older cached rows, or a stream from before this field existed.
export function isSkippedRow(row: AIEnrichmentRunRow): boolean {
    if (row.meta) {
        return Boolean(row.meta.skipped)
    }
    return Object.values(row.outputs ?? {}).some((value) => value === UNKNOWN_VERDICT)
}

function typeOfValue(value: boolean | number | string): AIEnrichmentOutputFieldType {
    if (typeof value === 'boolean') {
        return 'boolean'
    }
    if (typeof value === 'number') {
        return 'number'
    }
    return 'string'
}

// Columns are derived from the ndjson rows themselves rather than the editor's output_fields, so
// the results table renders correctly for both a live run (draft output_fields) and any future
// read of a saved version's results. Column order follows first-seen key order, which matches the
// backend's dict insertion order in format_run_row.
export function deriveOutputColumns(rows: AIEnrichmentRunRow[]): OutputColumnSpec[] {
    const order: string[] = []
    const typeByKey = new Map<string, AIEnrichmentOutputFieldType>()
    for (const row of rows) {
        if (!row.outputs) {
            continue
        }
        const rowSkipped = isSkippedRow(row)
        for (const [key, value] of Object.entries(row.outputs)) {
            if (!order.includes(key)) {
                order.push(key)
            }
            // A skipped row's values say nothing about the column's real type - if the first row
            // seen for a key were skipped, taking its type from that value would misrender every
            // later row's real boolean/number as a plain string. Keep scanning until a row
            // supplies an actual typed value.
            if (!typeByKey.has(key) && !rowSkipped && value !== UNKNOWN_VERDICT) {
                typeByKey.set(key, typeOfValue(value))
            }
        }
    }
    // A key seen only in skipped rows still needs a column; string is a reasonable default
    // renderer for it.
    return order.map((key) => ({ key, type: typeByKey.get(key) ?? 'string' }))
}

// A one-line summary of what was actually sent to the LLM for this row (post domain reduction),
// for the compact "Inputs" column - the full detail lives in the per-field tooltip the caller
// renders separately.
export function summarizeInputs(inputs: Record<string, unknown>): string {
    const entries = Object.entries(inputs)
    if (entries.length === 0) {
        return ''
    }
    return entries.map(([key, value]) => `${key}: ${value}`).join(', ')
}

// Pattern-matched plain-language summaries for the raw exception text backend/lab.py's
// _run_error renders (e.g. "AuthenticationError: litellm.AuthenticationError: ..."). The row's
// full raw error stays available in the cell's hover tooltip; this is only what's shown by
// default, so a staff user doesn't have to parse an SDK exception repr to know what to do next.
const ERROR_SUMMARIES: { pattern: RegExp; summary: string }[] = [
    {
        pattern: /AuthenticationError|\b401\b/i,
        summary: 'Authentication failed for this model. Check the API key configuration.',
    },
    { pattern: /RateLimitError|\b429\b/i, summary: 'Rate limited by the model provider. Try again in a moment.' },
    {
        pattern: /APIConnectionError|Connection error|ECONNREFUSED/i,
        summary: "Couldn't reach the model gateway. Check the network connection.",
    },
    { pattern: /Timeout|timed out/i, summary: 'The model call timed out. Try again.' },
]

export function summarizeError(error: string): string {
    return ERROR_SUMMARIES.find(({ pattern }) => pattern.test(error))?.summary ?? error
}
