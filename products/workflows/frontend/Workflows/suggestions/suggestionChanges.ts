import type { HogFlow } from '../hogflows/types'

export interface SuggestedFieldChange {
    path: string
    label: string
    before: unknown
    after: unknown
}

export interface SuggestedStepChange {
    stepId: string
    stepName: string | null
    fields: SuggestedFieldChange[]
}

export interface SuggestedChanges {
    steps: SuggestedStepChange[]
    workflow: SuggestedFieldChange[]
}

export type SuggestedFieldView =
    | { kind: 'inline' }
    | { kind: 'diff'; language: 'html' | 'json' | 'plaintext'; original: string; modified: string }

// Every step input sits at `config.inputs.<name>.value`, so those segments say nothing to a reader.
const SILENT_SEGMENTS = new Set(['config', 'inputs', 'value'])

// A value longer than this does not fit on one line next to its replacement, so it gets a diff.
const INLINE_MAX_LENGTH = 80

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function readPath(source: unknown, segments: string[]): unknown {
    let current = source
    for (const segment of segments) {
        if (!isPlainObject(current)) {
            return undefined
        }
        current = current[segment]
    }
    return current
}

function labelFor(segments: string[]): string {
    const spoken = segments.filter((segment) => !SILENT_SEGMENTS.has(segment))
    return (spoken.length ? spoken : segments).join(' › ')
}

function leafChanges(patch: Record<string, unknown>, live: unknown, prefix: string[] = []): SuggestedFieldChange[] {
    const changes: SuggestedFieldChange[] = []
    for (const [key, value] of Object.entries(patch)) {
        const segments = [...prefix, key]
        if (isPlainObject(value) && Object.keys(value).length > 0) {
            changes.push(...leafChanges(value, live, segments))
            continue
        }
        const before = readPath(live, segments)
        // Approving reduces the patch to what differs, so a step sent whole must not read here as if
        // every field were an edit. A null leaf removes the key, which is nothing when it is absent.
        if (sameLeaf(before, value)) {
            continue
        }
        changes.push({
            path: segments.join('.'),
            label: labelFor(segments),
            before,
            after: value,
        })
    }
    return changes
}

function sameLeaf(before: unknown, after: unknown): boolean {
    if (after === null) {
        return before === undefined || before === null
    }
    if (before === undefined) {
        return false
    }
    return JSON.stringify(before) === JSON.stringify(after)
}

function fitsInline(value: unknown): boolean {
    if (typeof value === 'string') {
        return value.length <= INLINE_MAX_LENGTH && !value.includes('\n')
    }
    return !isPlainObject(value) && !Array.isArray(value)
}

function looksLikeHtml(change: SuggestedFieldChange): boolean {
    if (change.path.split('.').at(-1) === 'html') {
        return true
    }
    return [change.before, change.after].some((value) => typeof value === 'string' && /^\s*</.test(value))
}

// Minified email HTML can be one long line. A line break between adjacent tags lets the diff
// point at the changed tag, and it keeps HTML that already has line breaks as it is.
function splitAdjacentTags(html: string): string {
    return html.replace(/>(?=<)/g, '>\n')
}

export function describeFieldView(change: SuggestedFieldChange): SuggestedFieldView {
    const { before, after } = change
    if (fitsInline(before) && fitsInline(after)) {
        return { kind: 'inline' }
    }
    const isText = (value: unknown): boolean => typeof value === 'string' || value === undefined || value === null
    if (isText(before) && isText(after)) {
        const original = typeof before === 'string' ? before : ''
        const modified = typeof after === 'string' ? after : ''
        if (looksLikeHtml(change)) {
            return {
                kind: 'diff',
                language: 'html',
                original: splitAdjacentTags(original),
                modified: splitAdjacentTags(modified),
            }
        }
        return { kind: 'diff', language: 'plaintext', original, modified }
    }
    const asJson = (value: unknown): string =>
        value === undefined || value === null ? '' : JSON.stringify(value, null, 2)
    return { kind: 'diff', language: 'json', original: asJson(before), modified: asJson(after) }
}

export function describeSuggestedChanges(content: Record<string, unknown>, live: HogFlow | null): SuggestedChanges {
    const { actions, ...rest } = content
    const liveSteps = new Map((live?.actions ?? []).map((action) => [action.id, action]))

    const steps: SuggestedStepChange[] = []
    if (Array.isArray(actions)) {
        for (const step of actions) {
            if (!isPlainObject(step) || typeof step.id !== 'string') {
                continue
            }
            const { id, ...patch } = step
            const liveStep = liveSteps.get(id)
            steps.push({
                stepId: id,
                stepName: liveStep?.name ?? null,
                fields: leafChanges(patch, liveStep),
            })
        }
    }

    return { steps, workflow: leafChanges(rest, live) }
}
