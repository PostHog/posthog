import { useEffect, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { SurveyEventName } from 'lib/posthog-typed'

import { HogFlowAction } from '../types'

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
    const [localNames, setLocalNames] = useState<(string | undefined)[]>(items.map((item) => item.name))

    // Update local state when items change from external sources
    useEffect(() => {
        setLocalNames(items.map((item) => item.name))
    }, [items.length, items]) // Only update when number of items changes

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

export function isSurveyTriggerConfig(config: Extract<HogFlowAction, { type: 'trigger' }>['config']): boolean {
    if (config.type !== 'event') {
        return false
    }
    const events = config.filters?.events ?? []
    return events.length === 1 && events[0]?.id === SurveyEventName.SENT
}

export function getSelectedSurveyId(config: HogFlowAction['config']): string | null | 'any' {
    if (!('type' in config) || config.type !== 'event') {
        return null
    }
    const surveyIdProp = config.filters?.properties?.find((p: any) => p.key === '$survey_id')
    if (!surveyIdProp) {
        return null // No selection made
    }
    // If operator is 'is_set', it means "Any survey" was selected
    if (surveyIdProp.operator === 'is_set') {
        return 'any'
    }
    return surveyIdProp.value ?? null
}
