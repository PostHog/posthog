import AsyncStorage from '@react-native-async-storage/async-storage'
import { useSyncExternalStore } from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { useAuthStore } from '@/auth/authStore'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
import { createPersistHydrationGate } from '@/lib/persistHydration'

import {
    DEFAULT_LIVE_TRAFFIC_FILTERS,
    type LiveTrafficFilters,
    normalizeLiveTrafficFilters,
} from '@/model/liveTrafficFilters'

export type LivePreference = 'all' | 'web' | 'mobile'
interface LiveSelection {
    preference: LivePreference
    trafficFilters: LiveTrafficFilters
    showFilterBanner: boolean
}

interface LivePreferencesState {
    values: Record<string, LiveSelection>
}

const DEFAULT_SELECTION: LiveSelection = {
    preference: 'all',
    trafficFilters: DEFAULT_LIVE_TRAFFIC_FILTERS,
    showFilterBanner: true,
}

export function normalizeLivePreference(value: unknown): LivePreference {
    return value === 'web' || value === 'mobile' ? value : 'all'
}

function storedRecord(value: unknown): Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : {}
}

function storedSelection(value: unknown): LiveSelection {
    const selection = storedRecord(value)
    const filters = storedRecord(selection.trafficFilters)
    const text = (field: keyof LiveTrafficFilters): string => {
        const value = filters[field]
        return typeof value === 'string' ? value : ''
    }
    return {
        preference: normalizeLivePreference(selection.preference),
        trafficFilters: normalizeLiveTrafficFilters({
            excludeBots: filters.excludeBots === true,
            hostname: text('hostname'),
            pathPrefix: text('pathPrefix'),
            pathMode: filters.pathMode === 'exact' || filters.pathMode === 'prefix' ? filters.pathMode : undefined,
            channelType: text('channelType'),
            countryCode: text('countryCode'),
            deviceType: text('deviceType'),
            referringDomain: text('referringDomain'),
        }),
        showFilterBanner: selection.showFilterBanner !== false,
    }
}

const hydration = createPersistHydrationGate()

export const useLivePreferencesStore = create<LivePreferencesState>()(
    persist(() => ({ values: {} }), {
        name: 'posthog-mobile-live-preferences',
        storage: createJSONStorage(() => AsyncStorage),
        merge: (persisted, current) => ({
            ...current,
            values: Object.fromEntries(
                Object.entries(storedRecord(storedRecord(persisted).values)).map(([key, value]) => [
                    key,
                    storedSelection(value),
                ])
            ),
        }),
        onRehydrateStorage: () => () => hydration.settle(),
    })
)

export function useLivePreferencesHydrated(): boolean {
    return useSyncExternalStore(hydration.subscribe, hydration.isHydrated, hydration.isHydrated)
}

export function useLivePreference(): LiveSelection & {
    setPreference: (value: LivePreference) => void
    setLiveFilters: (preference: LivePreference, trafficFilters: LiveTrafficFilters, showFilterBanner?: boolean) => void
    setShowFilterBanner: (showFilterBanner: boolean) => void
} {
    const mode = useDataMode()
    const scope = useProjectScope()
    const userId = useAuthStore((state) => state.user?.uuid)
    const key =
        mode === 'demo' ? 'demo' : scope && userId ? JSON.stringify([scope.host, scope.projectId, userId]) : null
    const selection = useLivePreferencesStore((state) => (key && state.values[key]) || DEFAULT_SELECTION)

    const update = (changes: Partial<LiveSelection>): void => {
        if (!key) {
            return
        }
        const current = useLivePreferencesStore.getState().values[key] ?? DEFAULT_SELECTION
        const next = { ...current, ...changes }
        if (JSON.stringify(current.trafficFilters) === JSON.stringify(next.trafficFilters)) {
            next.trafficFilters = current.trafficFilters
        }
        if (
            current.preference === next.preference &&
            current.trafficFilters === next.trafficFilters &&
            current.showFilterBanner === next.showFilterBanner
        ) {
            return
        }
        useLivePreferencesStore.setState((state) => ({ values: { ...state.values, [key]: next } }))
    }

    return {
        ...selection,
        setPreference: (value) => update({ preference: normalizeLivePreference(value) }),
        setLiveFilters: (preference, trafficFilters, showFilterBanner) =>
            update({
                preference: normalizeLivePreference(preference),
                trafficFilters: normalizeLiveTrafficFilters(trafficFilters),
                ...(showFilterBanner !== undefined ? { showFilterBanner } : {}),
            }),
        setShowFilterBanner: (showFilterBanner) => update({ showFilterBanner }),
    }
}
