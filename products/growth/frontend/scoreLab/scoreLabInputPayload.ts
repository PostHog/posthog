import type { InputFieldsEnumApi } from '../generated/api.schemas'

export type ScoreLabInputMode = 'fields' | 'query'

export interface ScoreLabInputPayload {
    input_fields: InputFieldsEnumApi[]
    input_query: string | null
}

// A config is exactly one of `input_fields` or `input_query` - both are frozen fields hashed into
// the config's content_hash. Save, run, and the dirty check all derive the payload from here so they
// can't drift apart on what "the current input" actually is.
export function buildInputPayload(
    mode: ScoreLabInputMode,
    fields: InputFieldsEnumApi[],
    query: string
): ScoreLabInputPayload {
    return {
        input_fields: mode === 'fields' ? fields : [],
        input_query: mode === 'query' ? query : null,
    }
}

export function hasValidInput(mode: ScoreLabInputMode, fields: string[], query: string): boolean {
    return mode === 'fields' ? fields.length > 0 : query.trim().length > 0
}

export function inputDisabledReason(mode: ScoreLabInputMode, fields: string[], query: string): string | undefined {
    if (hasValidInput(mode, fields, query)) {
        return undefined
    }
    return mode === 'fields' ? 'Select at least one payload field' : 'Enter a HogQL query'
}
