import { createContext, useContext } from 'react'

/**
 * Provides the active scene `tabId` to children so they can mount the tab-aware
 * `tracingFiltersLogic` / `tracingDataLogic` instances under the right key.
 *
 * `undefined` is a valid value — kea falls back to the default-keyed instance, which
 * keeps the scene usable outside of an internal-tab context (e.g. Storybook).
 */
const TracingTabIdContext = createContext<string | undefined>(undefined)

export const TracingTabIdProvider = TracingTabIdContext.Provider

export function useTracingTabId(): string | undefined {
    return useContext(TracingTabIdContext)
}
