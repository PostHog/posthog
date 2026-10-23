import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { DisplayOptionCheckbox } from '~/queries/nodes/InsightViz/DisplayOptionCheckbox'

export function LifecyclePercentagesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { showPercentagesOnSeries } = useValues(insightVizDataLogic(insightProps))

    return (
        <DisplayOptionCheckbox
            label="Show percentages on series"
            checked={!!showPercentagesOnSeries}
            onChange={() => {
                updateInsightFilter({ showPercentagesOnSeries: !showPercentagesOnSeries })
            }}
        />
    )
}
