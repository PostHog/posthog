import { useActions, useValues } from 'kea'

import { ChartOptionSwitch } from 'lib/components/ChartOptions/ChartOptionSwitch'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function LifecyclePercentagesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { showPercentagesOnSeries } = useValues(insightVizDataLogic(insightProps))

    return (
        <ChartOptionSwitch
            label="Show percentages on series"
            checked={!!showPercentagesOnSeries}
            onChange={(checked) => updateInsightFilter({ showPercentagesOnSeries: checked })}
        />
    )
}
