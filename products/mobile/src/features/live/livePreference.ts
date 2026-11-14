import { create } from 'zustand'

import { addSessionEndTask } from '@/auth/authStore'
import { sessionGeneration } from '@/auth/tokens'
import { useProjectScope } from '@/auth/useProjectScope'

export type LivePreference = 'all' | 'web' | 'mobile'
const usePreferences = create<{ values: Record<string, LivePreference | 'auto' | 'both'> }>()(() => ({ values: {} }))
addSessionEndTask(() => usePreferences.setState({ values: {} }))

export function normalizeLivePreference(value: unknown): LivePreference {
    return value === 'web' || value === 'mobile' ? value : 'all'
}

export function useLivePreference(): { preference: LivePreference; setPreference: (value: LivePreference) => void } {
    const scope = useProjectScope()
    const key = `${sessionGeneration()}|${scope?.host ?? 'demo'}|${scope?.projectId ?? 'demo'}`
    const preference = usePreferences((state) => normalizeLivePreference(state.values[key]))
    const setPreference = (value: LivePreference): void => {
        usePreferences.setState((state) => ({ values: { ...state.values, [key]: value } }))
    }
    return { preference, setPreference }
}
