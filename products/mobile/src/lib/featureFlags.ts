import { create } from 'zustand'

import { useAuthStore } from '@/auth/authStore'

import { hostKind } from './environment'

export const FEATURE_FLAGS = {
    modelScoreSort: 'mobile-inbox-model-score-sort',
    sessionReplay: 'mobile-session-replay',
    errorTracking: 'mobile-error-tracking',
} as const

export type FeatureFlagKey = (typeof FEATURE_FLAGS)[keyof typeof FEATURE_FLAGS]

interface FeatureFlagsState {
    flags: Record<string, boolean | string>
}

const useFeatureFlagsStore = create<FeatureFlagsState>()(() => ({ flags: {} }))

// Expo inlines `EXPO_PUBLIC_*` variables at build time, so it must be read as a literal `process.env` member.
const FORCED_FLAGS_ENV: string = process.env.EXPO_PUBLIC_FEATURE_FLAGS ?? ''

// Dev builds only, so a release build never shows flagged UI the project did not turn on.
const FORCED_FLAGS: ReadonlySet<string> = new Set(
    __DEV__
        ? FORCED_FLAGS_ENV.split(',')
              .map((key) => key.trim())
              .filter(Boolean)
        : []
)

const LOCAL_DEVELOPMENT_FLAGS: ReadonlySet<FeatureFlagKey> = new Set([
    FEATURE_FLAGS.errorTracking,
    FEATURE_FLAGS.sessionReplay,
])

export function setFeatureFlags(flags: Record<string, boolean | string>): void {
    useFeatureFlagsStore.setState({ flags })
}

/** Remote flags default off. Local development and explicit development overrides can enable them sooner. */
export function useFeatureFlag(key: FeatureFlagKey): boolean {
    const value = useFeatureFlagsStore((state) => state.flags[key])
    const localDevelopment = useAuthStore(
        (state) => __DEV__ && state.status === 'signed_in' && state.host !== null && hostKind(state.host) === 'local'
    )
    return (
        FORCED_FLAGS.has(key) ||
        (localDevelopment && LOCAL_DEVELOPMENT_FLAGS.has(key)) ||
        (value !== undefined && value !== false)
    )
}

export function useMobileProductFlags(): { errors: boolean; replay: boolean } {
    return {
        errors: useFeatureFlag(FEATURE_FLAGS.errorTracking),
        replay: useFeatureFlag(FEATURE_FLAGS.sessionReplay),
    }
}
