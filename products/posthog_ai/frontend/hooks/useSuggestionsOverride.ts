import { useActions } from 'kea'
import { useEffect, useRef } from 'react'

import { uuid } from 'lib/utils/dom'

import type { SuggestionGroup } from '../components/suggestions/Suggestions'
import { suggestionsOverrideLogic } from '../logics/suggestionsOverrideLogic'

export interface UseSuggestionsOverrideOptions {
    /** When false, the provider is deregistered (defaults apply). Defaults to true. */
    active?: boolean
}

/**
 * Registers contextual composer suggestions into the global `suggestionsOverrideLogic` under a stable
 * per-mount provider id, so the composer's empty state shows them instead of the generic defaults.
 * Pass a module-level constant: the registration is keyed on array identity. Deregisters on unmount
 * or when `active: false`.
 */
export function useSuggestionsOverride(
    suggestions: readonly SuggestionGroup[] | null,
    options?: UseSuggestionsOverrideOptions
): void {
    const active = options?.active ?? true
    const { registerSuggestions, deregisterSuggestions } = useActions(suggestionsOverrideLogic)
    const providerIdRef = useRef<string>(`suggestions-${uuid()}`)

    useEffect(() => {
        const providerId = providerIdRef.current
        if (!active || !suggestions || suggestions.length === 0) {
            deregisterSuggestions(providerId)
            return
        }
        registerSuggestions(providerId, suggestions)
    }, [active, suggestions, registerSuggestions, deregisterSuggestions])

    useEffect(() => {
        const providerId = providerIdRef.current
        return () => deregisterSuggestions(providerId)
    }, [deregisterSuggestions])
}
