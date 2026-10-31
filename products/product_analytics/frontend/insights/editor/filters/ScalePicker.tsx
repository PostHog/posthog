import { useActions, useValues } from 'kea'

import { AxisScaleOption } from 'lib/components/ChartOptions/AxisScaleOption'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function ScalePicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { yAxisScaleType } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <AxisScaleOption
            value={yAxisScaleType === 'log10' ? 'log' : 'linear'}
            onChange={(scale) => updateInsightFilter({ yAxisScaleType: scale === 'log' ? 'log10' : 'linear' })}
        />
    )
}
