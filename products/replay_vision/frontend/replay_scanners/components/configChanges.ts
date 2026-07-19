import { identifierToHuman } from 'lib/utils/strings'

export interface ScannerConfigChange {
    field: string
    kind: 'prompt' | 'tags' | 'scale' | 'length' | 'flag'
    op: 'set' | 'add' | 'remove' | 'rename'
    before: unknown
    after: unknown
    rationale?: string
}

const KINDS = new Set<string>(['prompt', 'tags', 'scale', 'length', 'flag'])
const OPS = new Set<string>(['set', 'add', 'remove', 'rename'])

function isConfigChange(candidate: unknown): candidate is ScannerConfigChange {
    if (!candidate || typeof candidate !== 'object') {
        return false
    }
    const record = candidate as Record<string, unknown>
    return typeof record.field === 'string' && KINDS.has(record.kind as string) && OPS.has(record.op as string)
}

/** Defensive: `changes` comes from a JSON field typed `unknown`, so junk entries must be dropped, not thrown on. */
export function parseConfigChanges(changes: unknown): ScannerConfigChange[] {
    if (!Array.isArray(changes)) {
        return []
    }
    return changes.filter(isConfigChange)
}

/** Humanizes a change value for the compact "field: before to after" line: booleans read on/off, a scale reads as its range. */
export function formatChangeValue(value: unknown): string {
    if (typeof value === 'boolean') {
        return value ? 'on' : 'off'
    }
    if (value && typeof value === 'object' && 'min' in value && 'max' in value) {
        const scale = value as { min: unknown; max: unknown; label?: unknown }
        const range = `${formatChangeValue(scale.min)}-${formatChangeValue(scale.max)}`
        return scale.label ? `${range} (${String(scale.label)})` : range
    }
    return String(value)
}

/** The distinct fields a recommendation changes, each with its kind. Field and kind are 1:1, so one row per field. */
export function changedFields(changes: ScannerConfigChange[]): { field: string; kind: ScannerConfigChange['kind'] }[] {
    const seen = new Set<string>()
    const fields: { field: string; kind: ScannerConfigChange['kind'] }[] = []
    for (const change of changes) {
        if (!seen.has(change.field)) {
            seen.add(change.field)
            fields.push({ field: change.field, kind: change.kind })
        }
    }
    return fields
}

export type FieldEditorKind = 'prompt' | 'tags' | 'scale' | 'length' | 'flag' | 'text'

export interface FieldEditorMeta {
    kind: FieldEditorKind
    label: string
    description?: string
}

// Labels and descriptions mirror the scanner configuration editor so both surfaces read the same.
const FIELD_EDITORS: Record<string, FieldEditorMeta> = {
    prompt: { kind: 'prompt', label: 'Prompt' },
    tags: { kind: 'tags', label: 'Tag vocabulary' },
    scale: { kind: 'scale', label: 'Scale' },
    length: { kind: 'length', label: 'Summary length' },
    multi_label: {
        kind: 'flag',
        label: 'Allow multiple tags per session',
        description: 'Otherwise the model picks exactly one tag from your vocabulary.',
    },
    allow_freeform_tags: {
        kind: 'flag',
        label: 'Allow freeform tags',
        description: 'Lets the model emit tags outside your tag vocabulary.',
    },
    allow_inconclusive: {
        kind: 'flag',
        label: 'Allow inconclusive verdicts',
        description:
            "Lets the model answer inconclusive when the recording doesn't contain enough evidence to decide. " +
            'Otherwise it must commit to yes or no.',
    },
}

/** Editor kind and label for a config field, falling back on the value's type for unknown fields. */
export function fieldEditor(field: string, value: unknown): FieldEditorMeta {
    return (
        FIELD_EDITORS[field] ?? {
            kind: typeof value === 'boolean' ? 'flag' : 'text',
            label: identifierToHuman(field),
        }
    )
}

/** The current config with the user's edited field values laid over it. */
export function buildAppliedConfig(
    baseConfig: Record<string, unknown>,
    fieldValues: Record<string, unknown>
): Record<string, unknown> {
    return { ...baseConfig, ...fieldValues }
}

export function describeTagOp(change: ScannerConfigChange): { verb: 'Add' | 'Remove' | 'Rename'; text: string } {
    if (change.op === 'rename') {
        return { verb: 'Rename', text: `${String(change.before)} → ${String(change.after)}` }
    }
    if (change.op === 'remove') {
        return { verb: 'Remove', text: String(change.before) }
    }
    return { verb: 'Add', text: String(change.after) }
}
