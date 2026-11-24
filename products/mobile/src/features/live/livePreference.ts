import { create } from 'zustand'

import { addSessionEndTask } from '@/auth/authStore'
import { sessionGeneration } from '@/auth/tokens'
import { useProjectScope } from '@/auth/useProjectScope'

import {
    DEFAULT_LIVE_TRAFFIC_FILTERS,
    type LiveTrafficFilters,
    normalizeLiveTrafficFilters,
} from '@/model/liveTrafficFilters'

export type LivePreference = 'all' | 'web' | 'mobile'
interface LiveSelection {
    preference: LivePreference
    trafficFilters: LiveTrafficFilters
}

const DEFAULT_SELECTION: LiveSelection = { preference: 'all', trafficFilters: DEFAULT_LIVE_TRAFFIC_FILTERS }
const usePreferences = create<{ values: Record<string, LiveSelection> }>()(() => ({ values: {} }))
addSessionEndTask(() => usePreferences.setState({ values: {} }))

export function normalizeLivePreference(value: unknown): LivePreference {
    return value === 'web' || value === 'mobile' ? value : 'all'
}

export function useLivePreference(): LiveSelection & {
    setPreference: (value: LivePreference) => void
    setLiveFilters: (preference: LivePreference, trafficFilters: LiveTrafficFilters) => void
} {
    const scope = useProjectScope()
    const key = `${sessionGeneration()}|${scope?.host ?? 'demo'}|${scope?.projectId ?? 'demo'}`
    const selection = usePreferences((state) => state.values[key] ?? DEFAULT_SELECTION)
    const setLiveFilters = (value: LivePreference, filters: LiveTrafficFilters): void => {
        const preference = normalizeLivePreference(value)
        const trafficFilters = normalizeLiveTrafficFilters(filters)
        const current = usePreferences.getState().values[key] ?? DEFAULT_SELECTION
        if (
            current.preference === preference &&
            JSON.stringify(current.trafficFilters) === JSON.stringify(trafficFilters)
        ) {
            return
        }
        usePreferences.setState((state) => ({ values: { ...state.values, [key]: { preference, trafficFilters } } }))
    }
    return { ...selection, setPreference: (value) => setLiveFilters(value, selection.trafficFilters), setLiveFilters }
}
