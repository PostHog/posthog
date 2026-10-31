import { useActions, useValues } from 'kea'

import { ChartOptionNumberInput } from 'lib/components/ChartOptions/ChartOptionNumberInput'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { isTrendsQuery } from '~/queries/utils'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

export function ConfidenceLevelInput(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { confidenceLevel, showConfidenceIntervals } = useValues(trendsDataLogic(insightProps))
    const { querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    return (
        <div className="pl-4">
            <ChartOptionNumberInput
                label="Confidence level"
                info="A 95% confidence level means that for each data point, we are 95% confident that the true value is within the confidence interval."
                value={confidenceLevel}
                min={0}
                max={100}
                suffix="%"
                disabledReason={
                    !showConfidenceIntervals ? 'Confidence intervals are only available for line graphs' : undefined
                }
                onChange={(value) => {
                    if (isTrendsQuery(querySource)) {
                        updateQuerySource({
                            ...querySource,
                            trendsFilter: { ...querySource.trendsFilter, confidenceLevel: value ?? 95 },
                        })
                    }
                }}
            />
        </div>
    )
}
