import { useActions, useValues } from 'kea'

import { ChartOptionNumberInput } from 'lib/components/ChartOptions/ChartOptionNumberInput'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { isTrendsQuery } from '~/queries/utils'

import {
    INTERVAL_TO_DEFAULT_MOVING_AVERAGE_PERIOD,
    trendsDataLogic,
} from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

export function MovingAverageIntervalsInput(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { movingAverageIntervals, showMovingAverage } = useValues(trendsDataLogic(insightProps))
    const { querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    const interval = isTrendsQuery(querySource) ? querySource.interval || 'day' : 'day'

    return (
        <div className="pl-4">
            <ChartOptionNumberInput
                label="Intervals"
                info="The number of data points to use for calculating the moving average. A larger number will create a smoother line but with more lag. You can't use a number greater than the amount of intervals in your date range."
                value={movingAverageIntervals}
                min={2}
                suffix={`${interval}s`}
                disabledReason={
                    !showMovingAverage ? 'Moving averages are only available for line and area graphs' : undefined
                }
                onChange={(value) => {
                    if (isTrendsQuery(querySource)) {
                        updateQuerySource({
                            ...querySource,
                            trendsFilter: {
                                ...querySource.trendsFilter,
                                movingAverageIntervals: value ?? INTERVAL_TO_DEFAULT_MOVING_AVERAGE_PERIOD[interval],
                            },
                        })
                    }
                }}
            />
        </div>
    )
}
