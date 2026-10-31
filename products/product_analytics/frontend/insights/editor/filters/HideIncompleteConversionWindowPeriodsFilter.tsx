import { useActions, useValues } from 'kea'

import { ChartOptionSwitch } from 'lib/components/ChartOptions/ChartOptionSwitch'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { isFunnelsQuery } from '~/queries/utils'

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
        <ChartOptionSwitch
            label="Hide incomplete periods"
            info="Hides recent periods whose conversion window hasn't fully elapsed, so the trend isn't dragged down by entrants who still have time to convert."
            checked={hideIncompleteConversionWindowPeriods}
            onChange={(checked) => updateInsightFilter({ hideIncompleteConversionWindowPeriods: checked })}
        />
    )
}
