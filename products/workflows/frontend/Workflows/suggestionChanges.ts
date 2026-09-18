import type { HogFlow } from './hogflows/types'

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
        changes.push({
            path: segments.join('.'),
            label: labelFor(segments),
            before: readPath(live, segments),
            after: value,
        })
    }
    return changes
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
