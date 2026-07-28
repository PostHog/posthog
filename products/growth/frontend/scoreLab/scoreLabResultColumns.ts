import { ScoreLabRunRow } from './scoreLabLogic'
import { ScoreLabOutputFieldType } from './scoreLabOutputFields'

export interface OutputColumnSpec {
    key: string
    type: ScoreLabOutputFieldType
}

function typeOfValue(value: boolean | number | string): ScoreLabOutputFieldType {
    if (typeof value === 'boolean') {
        return 'boolean'
    }
    if (typeof value === 'number') {
        return 'number'
    }
    return 'string'
}

// Columns are derived from the ndjson rows themselves rather than the editor's output_fields,
// so the results table renders correctly for both a live run (draft output_fields) and any
// future read of a saved version's results. Column order follows first-seen key order, which
// matches the backend's dict insertion order in format_run_row.
export function deriveOutputColumns(rows: ScoreLabRunRow[]): OutputColumnSpec[] {
    const typeByKey = new Map<string, ScoreLabOutputFieldType>()
    for (const row of rows) {
        if (!row.outputs) {
            continue
        }
        for (const [key, value] of Object.entries(row.outputs)) {
            if (!typeByKey.has(key)) {
                typeByKey.set(key, typeOfValue(value))
            }
        }
    }
    return Array.from(typeByKey.entries()).map(([key, type]) => ({ key, type }))
}
