import { useActions, useValues } from 'kea'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function LifecyclePercentagesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { showPercentagesOnSeries } = useValues(insightVizDataLogic(insightProps))

    return (
        <LemonCheckbox
            className="p-1 px-2"
            checked={!!showPercentagesOnSeries}
            onChange={() => {
                updateInsightFilter({ showPercentagesOnSeries: !showPercentagesOnSeries })
            }}
            label={<span className="font-normal">Show percentages on series</span>}
            size="small"
        />
    )
}
