import { useActions, useValues } from 'kea'

import { ChartOptionToggleGroup } from 'lib/components/ChartOptions/ChartOptionToggleGroup'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ResultCustomizationBy } from '~/queries/schema/schema-general'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

export function ResultCustomizationByPicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { resultCustomizationBy } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(trendsDataLogic(insightProps))

    return (
        <ChartOptionToggleGroup
            value={resultCustomizationBy}
            onChange={(value) => updateInsightFilter({ resultCustomizationBy: value })}
            options={[
                { value: ResultCustomizationBy.Value, label: 'By name' },
                { value: ResultCustomizationBy.Position, label: 'By rank' },
            ]}
        />
    )
}
