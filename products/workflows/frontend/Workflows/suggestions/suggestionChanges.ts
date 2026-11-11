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
    isNew: boolean
    fields: SuggestedFieldChange[]
}

export interface GroupedStepFields {
    email: SuggestedFieldChange[]
    main: SuggestedFieldChange[]
    other: SuggestedFieldChange[]
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

// FNV-1a, enough to tell two payloads apart in a label.
function shortDigest(text: string): string {
    let hash = 0x811c9dc5
    for (let index = 0; index < text.length; index++) {
        hash = Math.imul(hash ^ text.charCodeAt(index), 0x01000193)
    }
    return (hash >>> 0).toString(16).padStart(8, '0')
}

// Inline images can be megabytes of base64 that hide the change and stall the diff. Their bytes
// say nothing a reader can judge, so the diff shows their size, plus a digest so a swapped image
// still shows as a change. Compare emails renders them.
function shortenDataUris(html: string): string {
    return html.replace(/data:([\w/+.-]+);base64,[A-Za-z0-9+/=\s]{200,}/g, (match, type: string) => {
        const kilobytes = Math.round((match.length * 3) / 4 / 1024)
        return `data:${type};base64,… (${kilobytes.toLocaleString()} KB, ${shortDigest(match)})`
    })
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
                original: splitAdjacentTags(shortenDataUris(original)),
                modified: splitAdjacentTags(shortenDataUris(modified)),
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
                stepName: liveStep?.name ?? (typeof patch.name === 'string' ? patch.name : null),
                isNew: liveStep === undefined,
                fields: leafChanges(patch, liveStep),
            })
        }
    }

    return { steps, workflow: leafChanges(rest, live) }
}

const EMAIL_HTML_PATH = /(^|\.)email\.value\.html$/
// The visual editor's layout state. The rendered emails show what it changes.
const EMAIL_DESIGN_PATH = /(^|\.)email\.value\.design(\.|$)/
// What a reader needs to judge a new step. Its other settings are mostly defaults.
const NEW_STEP_KEY_PATHS = new Set([
    'name',
    'config.inputs.email.value.subject',
    'config.inputs.email.value.preheader',
    'config.inputs.email.value.to.email',
])

function isEmpty(value: unknown): boolean {
    return (
        value === undefined ||
        value === null ||
        value === '' ||
        (Array.isArray(value) && value.length === 0) ||
        (isPlainObject(value) && Object.keys(value).length === 0)
    )
}

export function groupStepFields(step: SuggestedStepChange): GroupedStepFields {
    const grouped: GroupedStepFields = { email: [], main: [], other: [] }
    for (const field of step.fields) {
        if (EMAIL_HTML_PATH.test(field.path)) {
            grouped.email.push(field)
        } else if (EMAIL_DESIGN_PATH.test(field.path)) {
            grouped.other.push(field)
        } else if (!step.isNew) {
            grouped.main.push(field)
        } else if (!isEmpty(field.after)) {
            grouped[NEW_STEP_KEY_PATHS.has(field.path) ? 'main' : 'other'].push(field)
        }
    }
    return grouped
}
