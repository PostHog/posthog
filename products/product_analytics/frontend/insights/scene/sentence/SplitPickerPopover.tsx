import { useActions, useValues } from 'kea'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { ChartDisplayType } from '~/types'
import type { InsightLogicProps } from '~/types'

import { propertyPickerBreakdownFilter } from './propertyPickerBreakdownFilter'
import { PropertyPickerPopover } from './PropertyPickerPopover'

export interface SplitPickerPopoverProps {
    insightProps: InsightLogicProps
    breakdownType?: string
    breakdownValue?: string | number | null
    trigger: (open: boolean, toggle: () => void) => JSX.Element
}

export function SplitPickerPopover({
    insightProps,
    breakdownType,
    breakdownValue,
    trigger,
}: SplitPickerPopoverProps): JSX.Element {
    const { breakdownFilter, display, isTrends } = useValues(insightVizDataLogic(insightProps))
    const { updateBreakdownFilter, updateDisplay } = useActions(insightVizDataLogic(insightProps))

    const previous = breakdownValue != null && breakdownType ? { value: breakdownValue, type: breakdownType } : null

    return (
        <PropertyPickerPopover
            insightProps={insightProps}
            value={previous ? { key: String(previous.value), type: previous.type } : null}
            onPick={(picked) => {
                const update = propertyPickerBreakdownFilter(breakdownFilter, picked, previous, isTrends)
                if (!update) {
                    return
                }
                updateBreakdownFilter(update)
                // A world map only renders a single country code breakdown.
                if (
                    isTrends &&
                    display === ChartDisplayType.WorldMap &&
                    (update.breakdowns?.length !== 1 || update.breakdowns[0].property !== '$geoip_country_code')
                ) {
                    updateDisplay(undefined)
                }
            }}
            trigger={trigger}
        />
    )
}
