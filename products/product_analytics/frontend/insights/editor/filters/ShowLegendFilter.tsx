import { useActions, useValues } from 'kea'

import { LegendOption } from 'lib/components/ChartOptions/LegendOption'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function ShowLegendFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { showLegend } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <LegendOption
            showLegend={!!showLegend}
            onShowLegendChange={(checked) => updateInsightFilter({ showLegend: checked })}
        />
    )
}
