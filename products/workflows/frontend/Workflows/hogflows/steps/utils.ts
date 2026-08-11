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

/**
 * Percentages for an even N-way cohort split, summing to exactly 100.
 *
 * Shares are allocated in hundredths of a percent rather than whole percents, because whole percents
 * can't divide 100 evenly for most counts and the runtime routes any shortfall to the last cohort
 * (see getRandomCohort). Allocating in whole percents therefore gave 30 cohorts ten shares of 4% and
 * twenty of 3%, so a third of the branches carried 33% more than the rest. The leftover hundredths
 * are spread one each across the leading cohorts, which keeps every share within 0.01 of its fair
 * value.
 */
export function normalizeCohortPercentages(count: number): number[] {
    if (count <= 0) {
        return []
    }
    const hundredthsPerPercent = 100
    const totalHundredths = 100 * hundredthsPerPercent
    const base = Math.floor(totalHundredths / count)
    const leftover = totalHundredths - base * count
    return Array.from({ length: count }, (_, i) => (base + (i < leftover ? 1 : 0)) / hundredthsPerPercent)
}

// Adding floats accumulates error, so a set of shares that ought to total 100 can land a hair off (an
// even thirty-way split sums to 99.99999999999997). Anything under this counts as that noise. The
// bound is three orders of magnitude above the worst error an even split accumulates at any workable
// branch count, and far below a difference anyone would type, so a real imbalance still registers.
const FLOAT_SUM_TOLERANCE = 1e-9

/** Whether a set of cohort shares adds up to a whole 100%, ignoring float summing error. */
export function cohortPercentagesAddUp(percentages: number[]): boolean {
    const total = percentages.reduce((sum, percentage) => sum + percentage, 0)
    return Math.abs(total - 100) < FLOAT_SUM_TOLERANCE
}

/**
 * Read a percentage field's raw text into the value to store, clamped to the 0-100 the field declares.
 *
 * The clamp is load-bearing: min/max on a number input only gate form validation, which this field is
 * not wired to, so without it any out-of-range text a browser accepts as a number gets persisted.
 * Scientific notation is the easy one to miss, since "1e5" is valid input to a number field.
 */
export function parseCohortPercentage(value: string): number {
    const parsed = Number.parseFloat(value)
    if (!Number.isFinite(parsed)) {
        return 0
    }
    return Math.min(100, Math.max(0, parsed))
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
