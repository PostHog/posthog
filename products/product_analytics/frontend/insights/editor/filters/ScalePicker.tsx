import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { DisplayOptionToggleGroup } from 'products/product_analytics/frontend/insights/editor/DisplayOptionToggleGroup'

export function ScalePicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { yAxisScaleType } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <DisplayOptionToggleGroup
            onChange={(value) => updateInsightFilter({ yAxisScaleType: value as 'linear' | 'log10' })}
            value={yAxisScaleType || 'linear'}
            options={[
                { value: 'linear', label: 'Linear' },
                { value: 'log10', label: 'Logarithmic' },
            ]}
        />
    )
}
