import { create } from 'zustand'

import { addSessionEndTask } from '@/auth/authStore'
import type { WebBreakdown, WebFilter, WebTileId, WebTrendMetric } from '@/model/views'

/** The screen's choices for one data scope (`demo`, or the host and project). */
export interface WebAnalyticsChoices {
    filters: WebFilter[]
    tabs: Partial<Record<WebTileId, WebBreakdown>>
    metric: WebTrendMetric
}

export const DEFAULT_WEB_CHOICES: WebAnalyticsChoices = { filters: [], tabs: {}, metric: 'visitors' }

interface WebAnalyticsStoreState {
    scopes: Record<string, WebAnalyticsChoices>
    update: (dataScope: string, change: (choices: WebAnalyticsChoices) => Partial<WebAnalyticsChoices>) => void
    clear: () => void
}

// In memory only, like the range: filters and tabs last for the session, per project, and are never saved anywhere.
export const useWebAnalyticsStore = create<WebAnalyticsStoreState>()((set) => ({
    scopes: {},
    update: (dataScope, change) =>
        set((state) => {
            const current = state.scopes[dataScope] ?? DEFAULT_WEB_CHOICES
            return { scopes: { ...state.scopes, [dataScope]: { ...current, ...change(current) } } }
        }),
    clear: () => set({ scopes: {} }),
}))

addSessionEndTask(() => useWebAnalyticsStore.getState().clear())

export function useWebAnalyticsChoices(dataScope: string): WebAnalyticsChoices {
    return useWebAnalyticsStore((state) => state.scopes[dataScope] ?? DEFAULT_WEB_CHOICES)
}
