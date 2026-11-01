import { useActions, useValues } from 'kea'

import { ValuesOnSeriesOption } from 'lib/components/ChartOptions/ValuesOnSeriesOption'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function ValueOnSeriesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { showValuesOnSeries } = useValues(insightVizDataLogic(insightProps))

    return (
        <ValuesOnSeriesOption
            checked={!!showValuesOnSeries}
            onChange={(checked) => updateInsightFilter({ showValuesOnSeries: checked })}
        />
    )
}
