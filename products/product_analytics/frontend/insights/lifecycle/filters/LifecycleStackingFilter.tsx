import { useActions, useValues } from 'kea'

import { ChartOptionSwitch } from 'lib/components/ChartOptions/ChartOptionSwitch'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function LifecycleStackingFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { lifecycleFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <ChartOptionSwitch
            label="Stack bars"
            checked={lifecycleFilter?.stacked ?? true}
            onChange={(checked) => updateInsightFilter({ stacked: checked })}
        />
    )
}
