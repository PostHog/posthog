import { useActions, useValues } from 'kea'

import { ChartOptionSwitch } from 'lib/components/ChartOptions/ChartOptionSwitch'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function ShowMultipleYAxesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showMultipleYAxes } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const toggleShowMultipleYAxes = (): void => {
        updateInsightFilter({ showMultipleYAxes: !showMultipleYAxes })
    }

    return (
        <ChartOptionSwitch
            label="Show multiple Y-axes"
            checked={!!showMultipleYAxes}
            onChange={toggleShowMultipleYAxes}
        />
    )
}
