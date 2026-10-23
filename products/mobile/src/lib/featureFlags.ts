import { create } from 'zustand'

export const FEATURE_FLAGS = { modelScoreSort: 'mobile-inbox-model-score-sort' } as const

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

export function setFeatureFlags(flags: Record<string, boolean | string>): void {
    useFeatureFlagsStore.setState({ flags })
}

/** False until flags load. A multivariate flag counts as on for any variant. */
export function useFeatureFlag(key: FeatureFlagKey): boolean {
    const value = useFeatureFlagsStore((state) => state.flags[key])
    return FORCED_FLAGS.has(key) || (value !== undefined && value !== false)
}
