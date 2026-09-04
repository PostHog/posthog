import { PropertyFilterType, PropertyOperator } from '~/types'

import { InternalEventTriggerConfig } from './slackTriggerFilters'

/** pinned: analytics event name emitted by the data modeling producer */
export const MATERIALIZATION_JOB_FINISHED_EVENT = '$materialization_job_finished'

/** Which outcome starts a run. Compiles to at most one exact filter on the event's `status`. */
export type MaterializationOutcome = 'any' | 'completed' | 'failed'

export const MATERIALIZATION_OUTCOME_OPTIONS: { value: MaterializationOutcome; label: string; description: string }[] =
    [
        { value: 'failed', label: 'Failed', description: 'Only runs that ended with an error.' },
        { value: 'completed', label: 'Completed', description: 'Only runs that published new data.' },
        { value: 'any', label: 'Completed or failed', description: 'Every run, whatever its outcome.' },
    ]

/**
 * Property keys the native controls own. Anything else a person adds survives untouched in the
 * advanced list, so the two editors never fight over the same entry.
 */
const OWNED_KEYS = new Set(['view_name', 'status'])

export interface MaterializationTriggerFilters {
    viewName: string | null
    outcome: MaterializationOutcome
    additional: Record<string, any>[]
}

// Callers pass whatever trigger a workflow carries, including legacy and malformed shapes, so
// every level is checked before it is read.
export function isMaterializationJobTriggerConfig(config: unknown): config is InternalEventTriggerConfig {
    if (!config || typeof config !== 'object') {
        return false
    }
    const { type, filters } = config as { type?: unknown; filters?: unknown }
    if (type !== 'internal-event' || !filters || typeof filters !== 'object') {
        return false
    }
    const { source, events } = filters as { source?: unknown; events?: unknown }
    return (
        source === 'internal-events' &&
        Array.isArray(events) &&
        events.some(
            (event) =>
                event &&
                typeof event === 'object' &&
                (event as { id?: unknown }).id === MATERIALIZATION_JOB_FINISHED_EVENT
        )
    )
}

function find(properties: Record<string, any>[], key: string): Record<string, any> | undefined {
    return properties.find((property) => property?.key === key)
}

function values(entry: Record<string, any> | undefined): string[] {
    if (!entry) {
        return []
    }
    const value = Array.isArray(entry.value) ? entry.value : [entry.value]
    return value.filter((item: unknown): item is string => typeof item === 'string' && item !== '')
}

function exact(key: string, value: string[]): Record<string, any> {
    return { key, value, operator: PropertyOperator.Exact, type: PropertyFilterType.Event }
}

export function decodeMaterializationFilters(
    properties: Record<string, any>[] | undefined
): MaterializationTriggerFilters {
    const list = Array.isArray(properties) ? properties : []
    const status = values(find(list, 'status'))[0]
    return {
        viewName: values(find(list, 'view_name'))[0] ?? null,
        outcome: status === 'completed' || status === 'failed' ? status : 'any',
        additional: list.filter((property) => !OWNED_KEYS.has(property?.key)),
    }
}

export function encodeMaterializationFilters(filters: MaterializationTriggerFilters): Record<string, any>[] {
    const properties: Record<string, any>[] = []
    if (filters.viewName) {
        properties.push(exact('view_name', [filters.viewName]))
    }
    if (filters.outcome !== 'any') {
        properties.push(exact('status', [filters.outcome]))
    }
    return [...properties, ...filters.additional]
}
