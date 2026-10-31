import { useActions, useValues } from 'kea'

import { ChartOptionSwitch } from 'lib/components/ChartOptions/ChartOptionSwitch'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function ShowAlertThresholdLinesFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { showAlertThresholdLines } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <ChartOptionSwitch
            label="Show alert threshold lines"
            checked={!!showAlertThresholdLines}
            onChange={(checked) => updateInsightFilter({ showAlertThresholdLines: checked })}
        />
    )
}
