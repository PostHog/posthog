import AsyncStorage from '@react-native-async-storage/async-storage'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { FEED_SOURCES, type FeedSettings, type FeedSource, type FeedUnit } from './feedModel'

/** Not interested hides a recording on this device. The list keeps the newest ids only. */
const HIDDEN_LIMIT = 500

interface StoredFeedSettings extends FeedSettings {
    unit: FeedUnit
    source: FeedSource
    hidden: string[]
}

interface FeedSettingsState extends StoredFeedSettings {
    set: (patch: Partial<StoredFeedSettings>) => void
    hide: (sessionId: string) => void
}

const DEFAULTS: StoredFeedSettings = {
    speed: 1,
    autoplayNext: true,
    startAt: 'key',
    leadInSeconds: 5,
    momentSeconds: 20,
    phoneFit: 'whole',
    skipInactivity: true,
    unit: 'moment',
    source: 'newest',
    hidden: [],
}

export const useFeedSettings = create<FeedSettingsState>()(
    persist(
        (set) => ({
            ...DEFAULTS,
            set: (patch) => set(patch),
            hide: (sessionId) =>
                set((state) => ({
                    hidden: [...state.hidden.filter((id) => id !== sessionId), sessionId].slice(-HIDDEN_LIMIT),
                })),
        }),
        {
            name: 'posthog-mobile-replay-feed-settings',
            version: 1,
            storage: createJSONStorage(() => AsyncStorage),
            partialize: ({ set: _set, hide: _hide, ...state }) => state,
            merge: (persisted, current) => {
                const stored =
                    typeof persisted === 'object' && persisted !== null
                        ? (persisted as Partial<StoredFeedSettings>)
                        : {}
                return {
                    ...current,
                    ...stored,
                    source: stored.source && FEED_SOURCES.includes(stored.source) ? stored.source : current.source,
                    hidden: Array.isArray(stored.hidden) ? stored.hidden : current.hidden,
                }
            },
        }
    )
)
