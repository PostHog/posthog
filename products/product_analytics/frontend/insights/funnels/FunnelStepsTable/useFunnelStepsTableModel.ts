import { useActions, useValues } from 'kea'

import { Sorting } from 'lib/lemon-ui/LemonTable/sorting'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { formatBreakdownLabel } from 'scenes/insights/utils'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { FlattenedFunnelStepByBreakdown } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'
import { getVisibilityKey } from '../funnelUtils'

export interface FunnelStepsTableModel {
    isOnlySeries: boolean
    allChecked: boolean
    someChecked: boolean
    toggleAll: () => void
    isChecked: (breakdown: FlattenedFunnelStepByBreakdown) => boolean
    breakdownLabel: (breakdown: FlattenedFunnelStepByBreakdown) => string
    sorting: Sorting | null
    setSorting: (sorting: Sorting | null) => void
}

export function useFunnelStepsTableModel(): FunnelStepsTableModel {
    const { insightProps } = useValues(insightLogic)
    const { breakdownFilter } = useValues(insightVizDataLogic(insightProps))
    const { flattenedBreakdowns, hiddenLegendBreakdowns, breakdownSorting } = useValues(funnelDataLogic(insightProps))
    const { setHiddenLegendBreakdowns, setBreakdownSorting } = useActions(funnelDataLogic(insightProps))
    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const isChecked = (breakdown: FlattenedFunnelStepByBreakdown): boolean =>
        !hiddenLegendBreakdowns?.includes(getVisibilityKey(breakdown.breakdown_value))
    const allChecked = flattenedBreakdowns?.every(isChecked)

    return {
        // Count values, not rows — compare mode shows one row per period for each value.
        isOnlySeries: flattenedBreakdowns.filter((b) => b.compare_label !== 'previous').length <= 1,
        allChecked,
        someChecked: flattenedBreakdowns?.some(isChecked),
        toggleAll: () =>
            // Either toggle all breakdowns on or off. Deduped — both rows of
            // a compare pair share one visibility key.
            setHiddenLegendBreakdowns(
                allChecked
                    ? Array.from(new Set(flattenedBreakdowns.map((b) => getVisibilityKey(b.breakdown_value))))
                    : []
            ),
        isChecked,
        breakdownLabel: (breakdown) => {
            // :KLUDGE: `BreakdownStepValues` is always wrapped into an array, which doesn't work for the
            // formatBreakdownLabel logic. Instead, we unwrap speculatively
            const value =
                breakdown.breakdown_value?.length == 1 ? breakdown.breakdown_value[0] : breakdown.breakdown_value

            // Pure-compare rows carry no breakdown value (their color/customization key
            // must match the chart bars), so fall back to the baseline label.
            return (
                formatBreakdownLabel(value, breakdownFilter, allCohorts.results, formatPropertyValueForDisplay) ||
                (breakdown.isBaseline ? 'Baseline' : '')
            )
        },
        // Sorting is controlled by the query's `funnelsFilter.breakdownSorting`, so it survives
        // saving/reloading and never touches the URL (a router push here would make the insight
        // scene reload the saved insight, discarding unsaved changes like the compare filter).
        sorting: breakdownSorting
            ? breakdownSorting.startsWith('-')
                ? { columnKey: breakdownSorting.slice(1), order: -1 }
                : { columnKey: breakdownSorting, order: 1 }
            : null,
        setSorting: (newSorting) =>
            // Format: 'column_key' or '-column_key' for descending
            setBreakdownSorting(
                newSorting
                    ? newSorting.order === -1
                        ? `-${newSorting.columnKey}`
                        : String(newSorting.columnKey)
                    : undefined
            ),
    }
}
