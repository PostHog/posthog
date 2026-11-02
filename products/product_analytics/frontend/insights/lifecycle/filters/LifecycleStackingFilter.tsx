import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { DisplayOptionCheckbox } from 'products/product_analytics/frontend/insights/editor/DisplayOptionCheckbox'

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
