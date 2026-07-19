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

export function describeTagOp(change: ScannerConfigChange): { verb: 'Add' | 'Remove' | 'Rename'; text: string } {
    if (change.op === 'rename') {
        return { verb: 'Rename', text: `${String(change.before)} → ${String(change.after)}` }
    }
    if (change.op === 'remove') {
        return { verb: 'Remove', text: String(change.before) }
    }
    return { verb: 'Add', text: String(change.after) }
}
