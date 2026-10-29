import AsyncStorage from '@react-native-async-storage/async-storage'
import { useMemo } from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { FEATURE_FLAGS, useFeatureFlag } from '@/lib/featureFlags'

import {
    CREATED_WINDOW_OPTIONS,
    type CreatedWindow,
    DEFAULT_INBOX_FILTERS,
    type InboxFilters,
    type InboxSort,
    MODEL_SCORE_SORT_OPTION,
    SORT_OPTIONS,
    SOURCE_FILTER_OPTIONS,
    type SourceFilterKey,
} from './filters'

interface InboxFiltersState {
    filters: InboxFilters
    setSort: (sort: InboxSort) => void
    setCreatedWindow: (window: CreatedWindow) => void
    toggleSource: (key: SourceFilterKey) => void
    clear: () => void
}

const SORTS: ReadonlySet<unknown> = new Set([...SORT_OPTIONS, MODEL_SCORE_SORT_OPTION].map((option) => option.key))
const WINDOWS: ReadonlySet<unknown> = new Set(CREATED_WINDOW_OPTIONS.map((option) => option.key))
const SOURCE_KEYS: ReadonlySet<unknown> = new Set(SOURCE_FILTER_OPTIONS.map((option) => option.key))

// Storage written by another build can hold a removed key or a different shape, so each field is checked on its own.
function storedInboxFilters(value: unknown): InboxFilters {
    const stored = typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {}
    return {
        sort: SORTS.has(stored.sort) ? (stored.sort as InboxSort) : DEFAULT_INBOX_FILTERS.sort,
        createdWindow: WINDOWS.has(stored.createdWindow)
            ? (stored.createdWindow as CreatedWindow)
            : DEFAULT_INBOX_FILTERS.createdWindow,
        sources: Array.isArray(stored.sources)
            ? [...new Set(stored.sources.filter((key): key is SourceFilterKey => SOURCE_KEYS.has(key)))]
            : DEFAULT_INBOX_FILTERS.sources,
    }
}

export const useInboxFiltersStore = create<InboxFiltersState>()(
    persist(
        (set) => ({
            filters: DEFAULT_INBOX_FILTERS,
            setSort: (sort) => set((state) => ({ filters: { ...state.filters, sort } })),
            setCreatedWindow: (createdWindow) => set((state) => ({ filters: { ...state.filters, createdWindow } })),
            toggleSource: (key) =>
                set((state) => {
                    const { sources } = state.filters
                    const next = sources.includes(key) ? sources.filter((source) => source !== key) : [...sources, key]
                    return { filters: { ...state.filters, sources: next } }
                }),
            clear: () => set({ filters: DEFAULT_INBOX_FILTERS }),
        }),
        {
            name: 'posthog-mobile-inbox-filters',
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state) => ({ filters: state.filters }),
            merge: (persisted, current) => ({
                ...current,
                filters: storedInboxFilters((persisted as { filters?: unknown } | undefined)?.filters),
            }),
        }
    )
)

/** The saved filters. A saved model score sort falls back to the default sort while its flag is off. */
export function useInboxFilters(): InboxFilters {
    const filters = useInboxFiltersStore((state) => state.filters)
    const modelScoreSort = useFeatureFlag(FEATURE_FLAGS.modelScoreSort)
    return useMemo(
        () =>
            filters.sort === 'model_score' && !modelScoreSort
                ? { ...filters, sort: DEFAULT_INBOX_FILTERS.sort }
                : filters,
        [filters, modelScoreSort]
    )
}
