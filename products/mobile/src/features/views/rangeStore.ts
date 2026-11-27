import AsyncStorage from '@react-native-async-storage/async-storage'
import { useCallback, useMemo } from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { addSessionEndTask, useAuthStore } from '@/auth/authStore'
import { haptic } from '@/lib/haptics'
import type { RangeChoice, RangePresetKey, SavedRange, ViewKind } from '@/model/views'

import {
    type RangeMethod,
    type RangeSheetEntry,
    trackDateRangeChanged,
    trackDateRangeCompared,
    trackDateRangeSheetOpened,
} from './analytics'
import { type FiltersOverride, rangeOverride } from './rangeOverride'
import { isSavedRange, presetForValues, rangeLabel } from './rangePresets'
import { type StepContext, type StepDirection, stepRange } from './rangeStep'

export type ViewRangeKey = string

export function useViewRangeScope(dataScope: string): string {
    const userId = useAuthStore((state) => state.user?.uuid)
    return dataScope !== 'demo' && userId ? `${dataScope}|${userId}` : dataScope
}

export function dashboardRangeKey(scope: string, dashboardRef: string | number): ViewRangeKey {
    return `${scope}|dashboard:${dashboardRef}`
}

export function insightRangeKey(scope: string, shortId: string): ViewRangeKey {
    return `${scope}|insight:${shortId}`
}

export function webAnalyticsRangeKey(scope: string): ViewRangeKey {
    return `${scope}|web`
}

interface ViewRangeStoreState {
    ranges: Record<ViewRangeKey, RangeChoice>
    setRange: (key: ViewRangeKey, choice: RangeChoice | null) => void
}

export const useViewRangeStore = create<ViewRangeStoreState>()(
    persist(
        (set) => ({
            ranges: {},
            setRange: (key, choice) =>
                set((state) => {
                    const { [key]: _removed, ...rest } = state.ranges
                    return { ranges: choice ? { ...rest, [key]: choice } : rest }
                }),
        }),
        {
            name: 'views-ranges:v1',
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state) => ({ ranges: state.ranges }),
            skipHydration: true,
        }
    )
)

export const viewRangesLoaded = Promise.resolve(useViewRangeStore.persist.rehydrate())

interface ViewCompareStoreState {
    compare: Record<ViewRangeKey, boolean>
    setCompare: (key: ViewRangeKey, on: boolean) => void
    clear: () => void
}

export const useViewCompareStore = create<ViewCompareStoreState>()((set) => ({
    compare: {},
    setCompare: (key, on) => set((state) => ({ compare: { ...state.compare, [key]: on } })),
    clear: () => set({ compare: {} }),
}))

addSessionEndTask(() => useViewCompareStore.getState().clear())

export interface ViewRange {
    /** Null: the view's saved range. */
    choice: RangeChoice | null
    /** The header label. Null when the saved range has no dates (each dashboard tile keeps its own). */
    label: string | null
    /** The saved range's label, which "Reset to saved range" returns to. Null as for `label`. */
    savedLabel: string | null
    /** The preset the range on screen matches, chosen or saved, so the sheet can mark its chip or row. */
    preset: RangePresetKey | null
    /** False makes "Reset to saved range" available in the range sheet. */
    isSaved: boolean
    /** The `filters_override` for dashboards and insights. Null reads the saved range. */
    override: FiltersOverride | null
    compare: boolean
    setChoice: (choice: RangeChoice, method: Exclude<RangeMethod, 'reset' | 'step'>) => void
    reset: () => void
    setCompare: (on: boolean) => void
    canStep: (direction: StepDirection, context: StepContext) => boolean
    /** Returns false when the step is not possible. */
    step: (direction: StepDirection, context: StepContext) => boolean
    /** Sends `mobile_date_range_sheet_opened`. The control owns the sheet, and this hook knows the view type. */
    noteSheetOpened: (entry: RangeSheetEntry) => void
}

/**
 * `savedCompare` is the view's own compare setting, used until the user toggles it.
 * `compareKey` keeps the compare toggle apart from a range that another view shares, such as a tile's insight.
 */
export function useViewRange(
    key: ViewRangeKey,
    viewType: ViewKind,
    saved: SavedRange,
    savedCompare = false,
    compareKey: ViewRangeKey = key
): ViewRange {
    const choice = useViewRangeStore((state) => state.ranges[key] ?? null)
    const compareChoice = useViewCompareStore((state) => state.compare[compareKey])
    const setRange = useViewRangeStore((state) => state.setRange)
    const setCompareFor = useViewCompareStore((state) => state.setCompare)
    const savedFrom = saved.dateFrom
    const savedTo = saved.dateTo
    const savedRange = useMemo<SavedRange>(() => ({ dateFrom: savedFrom, dateTo: savedTo }), [savedFrom, savedTo])
    const label = rangeLabel(choice, savedRange)

    const apply = useCallback(
        (next: RangeChoice | null, method: RangeMethod) => {
            trackDateRangeChanged({
                viewType,
                method,
                range: rangeLabel(next, savedRange) ?? 'saved',
                previousRange: rangeLabel(choice, savedRange) ?? 'saved',
            })
            setRange(key, next && !isSavedRange(next, savedRange) ? next : null)
        },
        [choice, key, savedRange, setRange, viewType]
    )

    return {
        choice,
        label,
        savedLabel: rangeLabel(null, savedRange),
        preset:
            choice?.kind === 'preset'
                ? choice.key
                : choice
                  ? null
                  : (presetForValues(savedRange.dateFrom, savedRange.dateTo)?.key ?? null),
        isSaved: isSavedRange(choice, savedRange),
        override: rangeOverride(choice),
        compare: compareChoice ?? savedCompare,
        setChoice: (next, method) => apply(next, method),
        reset: () => apply(null, 'reset'),
        setCompare: (on) => {
            trackDateRangeCompared({ viewType, enabled: on })
            setCompareFor(compareKey, on)
        },
        canStep: (direction, context) => stepRange(choice, savedRange, direction, context) !== null,
        step: (direction, context) => {
            const next = stepRange(choice, savedRange, direction, context)
            if (!next) {
                return false
            }
            haptic('selection')
            apply(next, 'step')
            return true
        },
        noteSheetOpened: (entry) => trackDateRangeSheetOpened({ viewType, entry }),
    }
}
