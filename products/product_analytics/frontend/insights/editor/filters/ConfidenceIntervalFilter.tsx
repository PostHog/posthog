import { useActions, useValues } from 'kea'

import { ChartOptionSwitch } from 'lib/components/ChartOptions/ChartOptionSwitch'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { isTrendsQuery } from '~/queries/utils'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

import { useLineGraphState } from './useLineGraphState'

export function ConfidenceIntervalFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { showConfidenceIntervals } = useValues(trendsDataLogic(insightProps))
    const { isLineGraph, isLinearScale } = useLineGraphState()

    return (
        <ChartOptionSwitch
            label="Show confidence intervals"
            checked={showConfidenceIntervals}
            disabledReason={
                !isLineGraph
                    ? 'Confidence intervals are only available for line graphs'
                    : !isLinearScale
                      ? 'Confidence intervals are only supported for linear scale.'
                      : undefined
            }
            onChange={(checked) => {
                if (isTrendsQuery(querySource)) {
                    updateQuerySource({
                        ...querySource,
                        trendsFilter: { ...trendsFilter, showConfidenceIntervals: checked },
                    })
                }
            }}
        />
    )
}
