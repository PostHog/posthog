import { useActions, useValues } from 'kea'

import { AxisLabelOption } from 'lib/components/ChartOptions/AxisLabelOption'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function AxisLabelFilter({ axis }: { axis: 'x' | 'y' }): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <AxisLabelOption
            value={axis === 'x' ? trendsFilter?.xAxisLabel : trendsFilter?.yAxisLabel}
            onChange={(label) => updateInsightFilter(axis === 'x' ? { xAxisLabel: label } : { yAxisLabel: label })}
            data-attr={`trends-${axis}-axis-label-input`}
        />
    )
}
