/**
 * Deterministic text rendering of a plan and of an apply receipt. Grouped by
 * object type and operation; deletes (including soft deletes) render first and
 * loud, creates show sentinel placeholders, updates list changed body fields.
 * No wall-clock reads — output depends only on the plan, so it is stable.
 */

import type { MutationOutcome, Plan, RecordedMutation } from './types'

type Operation = 'delete' | 'create' | 'update'

/** Optional current-object snapshots keyed by mutation sequence, for diffing updates. */
export type CurrentObjects = Record<number, Record<string, unknown>>

const OPERATION_ORDER: Operation[] = ['delete', 'create', 'update']
const DISPLAY_NAME_FIELDS = ['key', 'name', 'title', 'short_id', 'slug']
const NON_DISPLAY_UPDATE_FIELDS = new Set(['deleted'])

export function renderPlanText(plan: Plan, currentObjects: CurrentObjects = {}): string {
    if (plan.mutations.length === 0) {
        return 'No mutations planned.'
    }

    const lines: string[] = [`Plan: ${plan.mutations.length} mutation(s).`, '']
    for (const operation of OPERATION_ORDER) {
        const group = plan.mutations.filter((mutation) => operationOf(mutation) === operation)
        for (const mutation of sortForRender(group)) {
            lines.push(renderMutation(mutation, operation, currentObjects[mutation.sequence]))
        }
    }
    return lines.join('\n').trimEnd()
}

export function renderReceiptText(outcomes: MutationOutcome[]): string {
    if (outcomes.length === 0) {
        return 'No mutations applied.'
    }
    const lines = outcomes.map((outcome) => {
        const label = `${outcome.method} ${outcome.path}`
        if (outcome.status === 'applied') {
            return `[applied] ${label}`
        }
        if (outcome.status === 'failed') {
            return `[failed] ${label}${outcome.error ? ` — ${outcome.error}` : ''}`
        }
        return `[skipped] ${label}`
    })
    return lines.join('\n')
}

function operationOf(mutation: RecordedMutation): Operation {
    if (mutation.method === 'DELETE' || mutation.softDelete) {
        return 'delete'
    }
    if (mutation.method === 'POST') {
        return 'create'
    }
    return 'update'
}

/** Group deletes/creates/updates deterministically by object type then sequence. */
function sortForRender(group: RecordedMutation[]): RecordedMutation[] {
    return [...group].sort((a, b) => {
        const typeCompare = (a.objectType ?? '').localeCompare(b.objectType ?? '')
        return typeCompare !== 0 ? typeCompare : a.sequence - b.sequence
    })
}

function renderMutation(
    mutation: RecordedMutation,
    operation: Operation,
    currentObject: Record<string, unknown> | undefined
): string {
    const objectType = mutation.objectType ?? 'object'
    if (operation === 'delete') {
        return `DELETE ${objectType} ${displayName(mutation)}`
    }
    if (operation === 'create') {
        return `CREATE new ${objectType} #${mutation.sequence}`
    }
    return `UPDATE ${objectType} ${displayName(mutation)}${renderUpdateFields(mutation, currentObject)}`
}

function displayName(mutation: RecordedMutation): string {
    if (typeof mutation.body === 'object' && mutation.body !== null && !Array.isArray(mutation.body)) {
        const body = mutation.body as Record<string, unknown>
        for (const field of DISPLAY_NAME_FIELDS) {
            const value = body[field]
            if (typeof value === 'string' && value.length > 0) {
                return `"${value}"`
            }
        }
    }
    return `#${mutation.sequence}`
}

function renderUpdateFields(mutation: RecordedMutation, currentObject: Record<string, unknown> | undefined): string {
    if (typeof mutation.body !== 'object' || mutation.body === null || Array.isArray(mutation.body)) {
        return ''
    }
    const body = mutation.body as Record<string, unknown>
    const parts: string[] = []
    for (const key of Object.keys(body)) {
        if (NON_DISPLAY_UPDATE_FIELDS.has(key)) {
            continue
        }
        const next = formatScalar(body[key])
        if (currentObject && key in currentObject) {
            parts.push(`${key}: ${formatScalar(currentObject[key])} → ${next}`)
        } else {
            parts.push(`${key}: ${next}`)
        }
    }
    return parts.length > 0 ? ` (${parts.join(', ')})` : ''
}

function formatScalar(value: unknown): string {
    if (typeof value === 'string') {
        return value
    }
    if (typeof value === 'number' || typeof value === 'boolean' || value === null) {
        return String(value)
    }
    return JSON.stringify(value)
}
