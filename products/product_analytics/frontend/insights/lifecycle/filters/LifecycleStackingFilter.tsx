import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { DisplayOptionCheckbox } from '~/queries/nodes/InsightViz/DisplayOptionCheckbox'

export function LifecycleStackingFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { lifecycleFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <DisplayOptionCheckbox
            label="Stack bars"
            checked={lifecycleFilter?.stacked ?? true}
            onChange={(checked) => {
                updateInsightFilter({ stacked: checked })
            }}
        />
    )
}
