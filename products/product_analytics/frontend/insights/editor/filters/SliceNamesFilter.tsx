import { useActions, useValues } from 'kea'

import { ChartOptionSwitch } from 'lib/components/ChartOptions/ChartOptionSwitch'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

// Pie only — it's the one display that draws the series label on the chart itself.
export function SliceNamesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { showLabelOnSeries } = useValues(insightVizDataLogic(insightProps))

    return (
        <ChartOptionSwitch
            label="Show names on slices"
            checked={!!showLabelOnSeries}
            onChange={(checked) => updateInsightFilter({ showLabelsOnSeries: checked })}
        />
    )
}
