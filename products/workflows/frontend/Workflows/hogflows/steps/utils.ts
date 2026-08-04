import { useEffect, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { AnyPropertyFilter, PropertyFilterType } from '~/types'

import { HogFlow } from '../types'

type HogFlowEdge = HogFlow['edges'][number]

// The audience endpoint compiles filters against the persons table, so only person-scoped properties
// resolve. An event or group property comes back as a validation error rather than a count.
const COUNTABLE_PROPERTY_TYPES: string[] = [PropertyFilterType.Person, PropertyFilterType.Cohort]

/**
 * Whether a branch condition's filters can be counted as a share of persons. A condition evaluated
 * against an event rather than a person would produce a misleading percentage, so it gets no estimate.
 */
export function isCountableCondition(filters?: { properties?: unknown[] } | null): boolean {
    const properties = (filters?.properties ?? []) as AnyPropertyFilter[]
    // An unconfigured condition matches everyone, so an estimate of it carries no information.
    if (properties.length === 0) {
        return false
    }
    return properties.every((property) => property.type != null && COUNTABLE_PROPERTY_TYPES.includes(property.type))
}

/**
 * Check whether removing a branch edge at the given condition index would
 * orphan its target node (i.e. the target has no other incoming edges).
 * Returns a disabledReason string when removal should be blocked, or
 * undefined when removal is safe.
 */
export function getBranchRemovalDisabledReason(
    branchEdges: HogFlowEdge[],
    conditionIndex: number,
    edgesByActionId: Record<string, HogFlowEdge[]>
): string | undefined {
    const branchEdge = branchEdges.find((e) => e.index === conditionIndex)
    if (!branchEdge) {
        return undefined
    }
    const targetEdges = edgesByActionId[branchEdge.to] ?? []
    const hasOtherIncomingEdges = targetEdges.some((e) => e.to === branchEdge.to && e !== branchEdge)
    return hasOtherIncomingEdges ? undefined : 'Clean up branching steps first'
}

/** Filter out a branch edge by its index property and reindex the remaining edges. */
export function removeBranchEdge(branchEdges: HogFlowEdge[], conditionIndex: number): HogFlowEdge[] {
    return branchEdges.filter((e) => e.index !== conditionIndex).map((edge, i) => ({ ...edge, index: i }))
}

export function updateOptionalName<T>(obj: T & { name?: string }, name: string | undefined): T & { name?: string } {
    const updated = { ...obj }
    if (name) {
        updated.name = name
    } else {
        delete updated.name
    }
    return updated
}

export function updateItemWithOptionalName<T>(
    items: Array<T & { name?: string }>,
    index: number,
    name: string | undefined
): Array<T & { name?: string }> {
    return items.map((item, i) => {
        if (i !== index) {
            return item
        }
        return updateOptionalName(item, name)
    })
}

export function useDebouncedNameInputs<T extends { name?: string }>(
    items: T[],
    updateItems: (items: T[]) => void,
    debounceDelay: number = 300
): {
    localNames: (string | undefined)[]
    handleNameChange: (index: number, value: string | undefined) => void
} {
    const [localNames, setLocalNames] = useState<(string | undefined)[]>((items ?? []).map((item) => item.name))

    // Update local state when items change from external sources
    useEffect(() => {
        setLocalNames((items ?? []).map((item) => item.name))
    }, [items?.length, items]) // Only update when number of items changes

    // Debounced function to update items
    const debouncedUpdate = useDebouncedCallback((index: number, value: string | undefined) => {
        updateItems(updateItemWithOptionalName(items, index, value))
    }, debounceDelay)

    const handleNameChange = (index: number, value: string | undefined): void => {
        // Update local state immediately for responsive typing
        const newNames = [...localNames]
        newNames[index] = value
        setLocalNames(newNames)

        // Debounced update to persist the name
        debouncedUpdate(index, value)
    }

    return {
        localNames,
        handleNameChange,
    }
}

export function useDebouncedNameInput<T extends { name?: string }>(
    item: T,
    updateItem: (item: T) => void,
    debounceDelay: number = 300
): {
    localName: string | undefined
    handleNameChange: (value: string | undefined) => void
} {
    const [localName, setLocalName] = useState<string | undefined>(item.name)

    // Update local state when item changes from external sources
    useEffect(() => {
        setLocalName(item.name)
    }, [item.name])

    // Debounced function to update item
    const debouncedUpdate = useDebouncedCallback((value: string | undefined) => {
        updateItem(updateOptionalName(item, value))
    }, debounceDelay)

    const handleNameChange = (value: string | undefined): void => {
        // Update local state immediately for responsive typing
        setLocalName(value)

        // Debounced update to persist the name
        debouncedUpdate(value)
    }

    return {
        localName,
        handleNameChange,
    }
}
