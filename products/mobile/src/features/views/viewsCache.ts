import { type QueryClient, type QueryKey, skipToken, useQuery } from '@tanstack/react-query'
import { useCallback, useSyncExternalStore } from 'react'
import { create } from 'zustand'

import { BudgetExceededError } from '@/api/budget'
import { ApiError } from '@/api/client'
import { stableStringify } from '@/api/query'
import { queryClient as appQueryClient } from '@/api/queryClient'
import { type ProjectScope, scopeKey } from '@/api/reports'
import { missingScope } from '@/api/scopeErrors'
import { addSessionEndTask } from '@/auth/authStore'
import type { Freshness } from '@/model/views'

import { staleTimeFor } from './freshness'
import { viewsQueue } from './refreshQueue'

/** Query keys. Every key carries the host and project, so a project switch never shows another project's data. */
export const viewsKeys = {
    all: (scope: ProjectScope | null) => ['views', ...scopeKey(scope)] as const,
    shortcuts: (scope: ProjectScope | null) => [...viewsKeys.all(scope), 'shortcuts'] as const,
    recentDashboards: (scope: ProjectScope | null) => [...viewsKeys.all(scope), 'recent_dashboards'] as const,
    smartPinDisplays: (scope: ProjectScope | null, pins: string) =>
        [...viewsKeys.all(scope), 'smart_pin_displays', pins] as const,
    pinMetadata: (scope: ProjectScope | null, shortId: string) =>
        [...viewsKeys.all(scope), 'pin_metadata', shortId] as const,
    browseDashboards: (scope: ProjectScope | null) => [...viewsKeys.all(scope), 'browse', 'dashboards'] as const,
    browseInsights: (scope: ProjectScope | null) => [...viewsKeys.all(scope), 'browse', 'insights'] as const,
    searchDashboards: (scope: ProjectScope | null, search: string) =>
        [...viewsKeys.all(scope), 'search', 'dashboards', search] as const,
    searchInsights: (scope: ProjectScope | null, search: string) =>
        [...viewsKeys.all(scope), 'search', 'insights', search] as const,
    /** `ref` is the dashboard id as a string; `override` is `overrideKey(...)`. */
    dashboard: (scope: ProjectScope | null, ref: string, override: string) =>
        [...viewsKeys.all(scope), 'dashboard', ref, override] as const,
    insight: (scope: ProjectScope | null, shortId: string, dashboardRef: string | null, override: string) =>
        [...viewsKeys.all(scope), 'insight', shortId, dashboardRef ?? '-', override] as const,
    compare: (scope: ProjectScope | null, query: string) => [...viewsKeys.all(scope), 'compare', query] as const,
    webOverview: (scope: ProjectScope | null, query: string) => [...viewsKeys.all(scope), 'web', query] as const,
    actors: (scope: ProjectScope | null, query: string) => [...viewsKeys.all(scope), 'actors', query] as const,
}

/** Snapshots stay this long after the last screen showing them goes away, so tab switches repaint at once. */
export const SNAPSHOT_GC_MS = 30 * 60_000

appQueryClient.setQueryDefaults(['views'], { gcTime: SNAPSHOT_GC_MS })

export function overrideKey(override: Record<string, unknown> | null): string {
    return override ? stableStringify(override) : '-'
}

/** The queue's freshness key for a cache entry. */
export function freshnessKey(queryKey: QueryKey): string {
    return stableStringify(queryKey)
}

export function getSnapshot<T>(client: QueryClient, queryKey: QueryKey): T | undefined {
    return client.getQueryData<T>(queryKey)
}

export function setSnapshot<T>(client: QueryClient, queryKey: QueryKey, value: T): void {
    client.setQueryData<T>(queryKey, value)
}

/**
 * Subscribes to a cache entry that only the refresh queue writes. The query never fetches on its own, so mounting a
 * row or a tile sends nothing: the screen's refresh rules decide every request.
 */
export function useSnapshot<T>(queryKey: QueryKey | null): T | undefined {
    const result = useQuery<T>({
        queryKey: queryKey ?? ['views', 'none', 'idle'],
        queryFn: skipToken,
        // The same rule as the refresh passes, so `isStale` agrees with them.
        staleTime: (query) => staleTimeFor(query.state.data as Freshness | undefined, query.state.dataUpdatedAt),
    })
    return queryKey ? result.data : undefined
}

/** True while a request for this freshness key is queued or running, for a pin's progress line. */
export function useItemUpdating(key: string | null): boolean {
    const subscribe = useCallback((listener: () => void) => viewsQueue.subscribe(listener), [])
    return useSyncExternalStore(subscribe, () => (key ? viewsQueue.isKeyBusy(key) : false))
}

/**
 * Why an item has no fresh data. `deleted`: 404, "This view was deleted". `no_access`: 403 without a missing scope.
 * `scope`: the token lacks a Views scope; Views shows the sign-in state. `failed`: anything else.
 */
export type ItemErrorKind = 'deleted' | 'no_access' | 'scope' | 'failed'

export function itemErrorKind(error: unknown): ItemErrorKind | null {
    if (error instanceof Error && error.name === 'AbortError') {
        return null
    }
    if (error instanceof BudgetExceededError) {
        return null
    }
    if (error instanceof ApiError && error.status === 404) {
        return 'deleted'
    }
    if (error instanceof ApiError && error.status === 403) {
        return missingScope(error) ? 'scope' : 'no_access'
    }
    return 'failed'
}

interface ItemErrorsState {
    errors: Record<string, ItemErrorKind>
    set: (key: string, kind: ItemErrorKind) => void
    clear: (key: string) => void
    reset: () => void
}

export const useItemErrors = create<ItemErrorsState>()((set) => ({
    errors: {},
    set: (key, kind) =>
        set((state) => (state.errors[key] === kind ? state : { errors: { ...state.errors, [key]: kind } })),
    clear: (key) =>
        set((state) => {
            if (!(key in state.errors)) {
                return state
            }
            const { [key]: _removed, ...rest } = state.errors
            return { errors: rest }
        }),
    reset: () => set({ errors: {} }),
}))

addSessionEndTask(() => useItemErrors.getState().reset())

export function useItemError(key: string | null): ItemErrorKind | null {
    return useItemErrors((state) => (key ? (state.errors[key] ?? null) : null))
}
