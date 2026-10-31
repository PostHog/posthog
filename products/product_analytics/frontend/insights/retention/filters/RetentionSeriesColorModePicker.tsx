import { useActions, useValues } from 'kea'

import { ChartOptionToggleGroup } from 'lib/components/ChartOptions/ChartOptionToggleGroup'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function RetentionSeriesColorModePicker(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    if (!canEditInsight) {
        return null
    }

    const chartStyle = retentionFilter?.chartStyle

    return (
        <ChartOptionToggleGroup
            value={chartStyle?.seriesColorMode || 'palette'}
            onChange={(value) => updateInsightFilter({ chartStyle: { ...chartStyle, seriesColorMode: value } })}
            options={[
                { value: 'palette', label: 'One per cohort' },
                { value: 'opacity', label: 'One shade' },
            ]}
        />
    )
}
