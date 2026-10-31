import { useActions, useValues } from 'kea'

import { ChartOptionSwitch } from 'lib/components/ChartOptions/ChartOptionSwitch'
import { insightLogic } from 'scenes/insights/insightLogic'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

export function StackBreakdownFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(trendsDataLogic(insightProps))

    return (
        <ChartOptionSwitch
            label="Stack breakdown values"
            checked={!!trendsFilter?.stackBreakdownValues}
            onChange={(checked) => updateInsightFilter({ stackBreakdownValues: checked })}
        />
    )
}
