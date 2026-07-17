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

export function describeTagOp(change: ScannerConfigChange): { verb: 'Add' | 'Remove' | 'Rename'; text: string } {
    if (change.op === 'rename') {
        return { verb: 'Rename', text: `${String(change.before)} → ${String(change.after)}` }
    }
    if (change.op === 'remove') {
        return { verb: 'Remove', text: String(change.before) }
    }
    return { verb: 'Add', text: String(change.after) }
}
