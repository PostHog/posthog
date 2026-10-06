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

// Every step input sits at `config.inputs.<name>.value`, so those segments say nothing to a reader.
const SILENT_SEGMENTS = new Set(['config', 'inputs', 'value'])

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
