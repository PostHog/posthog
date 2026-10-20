import { PropertyFilterType, PropertyOperator } from '~/types'

/** pinned: internal event the alerts platform emits for each alert transition */
export const ALERT_TRANSITION_EVENT = '$alert_transition'

/** The stored trigger config an alert workflow uses. */
export type InternalEventAlertTriggerConfig = {
    type: 'internal-event'
    filters: {
        source: 'internal-events'
        events: { id: string; type: 'events' }[]
        properties?: any[]
    }
}

export const ALERT_TRANSITION_OPTIONS: { value: string; label: string }[] = [
    { value: 'firing', label: 'Starts firing' },
    { value: 'resolved', label: 'Resolves' },
    { value: 'errored', label: 'Check fails' },
    { value: 'broken', label: 'Stops checking after repeated failures' },
]

export interface AlertTriggerFilters {
    alertIds: string[]
    // Empty means every transition.
    transitions: string[]
}

// Callers pass whatever trigger a workflow carries, including malformed shapes, so every level is
// checked before it is read.
export function isAlertTransitionTriggerConfig(config: unknown): config is InternalEventAlertTriggerConfig {
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
            (event) => event && typeof event === 'object' && (event as { id?: unknown }).id === ALERT_TRANSITION_EVENT
        )
    )
}

function values(properties: Record<string, any>[], key: string): string[] {
    const entry = properties.find((property) => property?.key === key)
    if (!entry) {
        return []
    }
    const value = Array.isArray(entry.value) ? entry.value : [entry.value]
    return value.filter((item: unknown): item is string => typeof item === 'string' && item !== '')
}

function exact(key: string, value: string[]): Record<string, any> {
    return { key, value, operator: PropertyOperator.Exact, type: PropertyFilterType.Event }
}

export function decodeAlertFilters(properties: Record<string, any>[] | undefined): AlertTriggerFilters {
    const list = Array.isArray(properties) ? properties : []
    return {
        alertIds: values(list, 'alert_configuration_id'),
        transitions: values(list, 'transition'),
    }
}

export function encodeAlertFilters(filters: AlertTriggerFilters): Record<string, any>[] {
    const properties: Record<string, any>[] = []
    if (filters.alertIds.length) {
        properties.push(exact('alert_configuration_id', filters.alertIds))
    }
    if (filters.transitions.length) {
        properties.push(exact('transition', filters.transitions))
    }
    return properties
}
