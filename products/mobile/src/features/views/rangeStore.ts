import { useCallback, useMemo } from 'react'
import { create } from 'zustand'

import { addSessionEndTask } from '@/auth/authStore'
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

/**
 * `{data scope}|dashboard:{id}`, `{data scope}|insight:{short_id}` or `{data scope}|web`. The data scope
 * (`useViewsContext().dataScope`) keeps a range picked in demo mode or in one project out of the others.
 */
export type ViewRangeKey = string

export function dashboardRangeKey(dataScope: string, dashboardRef: string | number): ViewRangeKey {
    return `${dataScope}|dashboard:${dashboardRef}`
}

export function insightRangeKey(dataScope: string, shortId: string): ViewRangeKey {
    return `${dataScope}|insight:${shortId}`
}

export function webAnalyticsRangeKey(dataScope: string): ViewRangeKey {
    return `${dataScope}|web`
}

interface ViewRangeStoreState {
    ranges: Record<ViewRangeKey, RangeChoice>
    compare: Record<ViewRangeKey, boolean>
    setRange: (key: ViewRangeKey, choice: RangeChoice | null) => void
    setCompare: (key: ViewRangeKey, on: boolean) => void
    clear: () => void
}

// In memory only: a range lasts for the session, like the web's draft filters, and is never saved to the view.
export const useViewRangeStore = create<ViewRangeStoreState>()((set) => ({
    ranges: {},
    compare: {},
    setRange: (key, choice) =>
        set((state) => {
            const { [key]: _removed, ...rest } = state.ranges
            return { ranges: choice ? { ...rest, [key]: choice } : rest }
        }),
    setCompare: (key, on) => set((state) => ({ compare: { ...state.compare, [key]: on } })),
    clear: () => set({ ranges: {}, compare: {} }),
}))

addSessionEndTask(() => useViewRangeStore.getState().clear())

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
 * The session range of one view. `savedCompare` is the view's own compare setting, used until the user toggles it.
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
    const compareChoice = useViewRangeStore((state) => state.compare[compareKey])
    const setRange = useViewRangeStore((state) => state.setRange)
    const setCompareFor = useViewRangeStore((state) => state.setCompare)
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
