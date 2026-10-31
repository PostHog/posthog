import { useActions, useValues } from 'kea'

import { PercentOfTotalOption } from 'lib/components/ChartOptions/PercentOfTotalOption'
import { insightLogic } from 'scenes/insights/insightLogic'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

export function PercentStackViewFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showPercentStackView } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(trendsDataLogic(insightProps))

    return (
        <PercentOfTotalOption
            checked={!!showPercentStackView}
            onChange={(checked) => updateInsightFilter({ showPercentStackView: checked })}
        />
    )
}
