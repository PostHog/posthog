import AsyncStorage from '@react-native-async-storage/async-storage'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { addSessionEndTask } from '@/auth/authStore'

export type ChatRating = 'good' | 'bad'

interface ChatFeedbackState {
    responses: Record<string, { rating: ChatRating; feedbackSent: boolean }>
    hydrated: boolean
    setHydrated: () => void
    rate: (key: string, rating: ChatRating) => boolean
    markFeedbackSent: (key: string) => boolean
    clear: () => void
}

export const useChatFeedbackStore = create<ChatFeedbackState>()(
    persist(
        (set, get) => ({
            responses: {},
            hydrated: false,
            setHydrated: () => set({ hydrated: true }),
            rate: (key, rating) => {
                if (!get().hydrated || get().responses[key]) return false
                set((state) => ({
                    responses: Object.fromEntries(
                        Object.entries({ ...state.responses, [key]: { rating, feedbackSent: false } }).slice(-1000)
                    ),
                }))
                return true
            },
            markFeedbackSent: (key) => {
                const response = get().responses[key]
                if (!response || response.rating !== 'bad' || response.feedbackSent) return false
                set((state) => ({ responses: { ...state.responses, [key]: { ...response, feedbackSent: true } } }))
                return true
            },
            clear: () => set({ responses: {} }),
        }),
        {
            name: 'posthog-mobile-chat-feedback',
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state) => ({ responses: state.responses }),
            onRehydrateStorage: (state) => () => state.setHydrated(),
        }
    )
)

addSessionEndTask(() => useChatFeedbackStore.getState().clear())
