import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { isFunnelsQuery } from '~/queries/schema/node-guards'

import { DisplayOptionCheckbox } from 'products/product_analytics/frontend/insights/editor/DisplayOptionCheckbox'

export function HideIncompleteConversionWindowPeriodsFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    if (!isFunnelsQuery(querySource)) {
        return null
    }

    const hideIncompleteConversionWindowPeriods =
        querySource.funnelsFilter?.hideIncompleteConversionWindowPeriods ?? false

    return (
        <DisplayOptionCheckbox
            label="Hide incomplete periods"
            info="Hides recent periods whose conversion window hasn't fully elapsed, so the trend isn't dragged down by entrants who still have time to convert."
            checked={hideIncompleteConversionWindowPeriods}
            onChange={() =>
                updateInsightFilter({
                    hideIncompleteConversionWindowPeriods: !hideIncompleteConversionWindowPeriods,
                })
            }
        />
    )
}
