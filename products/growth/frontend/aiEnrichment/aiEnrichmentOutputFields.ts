import type { OutputFieldApi, OutputFieldTypeEnumApi } from '../generated/api.schemas'

export type AIEnrichmentOutputFieldType = OutputFieldTypeEnumApi

// The editor always carries a description (blank while unset), where the API leaves it optional.
export interface AIEnrichmentOutputField extends OutputFieldApi {
    description: string
}

// The classifier's whole output contract: these are the keys the prompt asks the model for and
// the only keys a stored verdict carries. The label is a human name and is never one of them, so
// renaming a label changes nothing about what a version computes.
export const DEFAULT_OUTPUT_FIELD_SEED: AIEnrichmentOutputField[] = [
    { key: 'verdict', type: 'boolean', description: 'Whether this company matches the label.' },
    { key: 'confidence', type: 'number', description: 'Confidence in the verdict, from 0 to 1.' },
    { key: 'reasoning', type: 'string', description: 'Brief reasoning for the verdict.' },
]

// Half-typed rows are a normal editor state, so they're dropped rather than sent. Save, run, and
// the enabled/disabled check all go through here so they can't disagree on what will be submitted.
export function buildOutputFieldsPayload(fields: AIEnrichmentOutputField[]): AIEnrichmentOutputField[] {
    return fields.filter((field) => field.key.trim().length > 0)
}

export function hasValidOutputFields(fields: AIEnrichmentOutputField[]): boolean {
    return buildOutputFieldsPayload(fields).length > 0
}

export function outputFieldsDisabledReason(fields: AIEnrichmentOutputField[]): string | undefined {
    return hasValidOutputFields(fields) ? undefined : 'Add at least one output field'
}
