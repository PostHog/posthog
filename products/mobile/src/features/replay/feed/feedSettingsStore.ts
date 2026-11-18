import AsyncStorage from '@react-native-async-storage/async-storage'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import type { FeedSettings, FeedSource, FeedUnit } from './feedModel'

interface FeedSettingsState extends FeedSettings {
    unit: FeedUnit
    source: FeedSource
    set: (patch: Partial<FeedSettings & { unit: FeedUnit; source: FeedSource }>) => void
}

const DEFAULTS: FeedSettings & { unit: FeedUnit; source: FeedSource } = {
    speed: 1,
    autoplayNext: true,
    startAt: 'key',
    leadInSeconds: 5,
    momentSeconds: 20,
    phoneFit: 'whole',
    unit: 'moment',
    source: 'newest',
}

export const useFeedSettings = create<FeedSettingsState>()(
    persist((set) => ({ ...DEFAULTS, set: (patch) => set(patch) }), {
        name: 'posthog-mobile-replay-feed-settings',
        version: 1,
        storage: createJSONStorage(() => AsyncStorage),
        partialize: ({ set: _set, ...state }) => state,
        merge: (persisted, current) => ({
            ...current,
            ...(typeof persisted === 'object' && persisted !== null ? (persisted as Partial<FeedSettingsState>) : {}),
        }),
    })
)
