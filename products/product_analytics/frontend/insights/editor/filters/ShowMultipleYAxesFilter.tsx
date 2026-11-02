import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { DisplayOptionCheckbox } from 'products/product_analytics/frontend/insights/editor/DisplayOptionCheckbox'

export function ShowMultipleYAxesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showMultipleYAxes } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const toggleShowMultipleYAxes = (): void => {
        updateInsightFilter({ showMultipleYAxes: !showMultipleYAxes })
    }

    return (
        <DisplayOptionCheckbox
            label="Show multiple Y-axes"
            checked={!!showMultipleYAxes}
            onChange={toggleShowMultipleYAxes}
        />
    )
}
