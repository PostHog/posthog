import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { DisplayOptionCheckbox } from 'products/product_analytics/frontend/insights/editor/DisplayOptionCheckbox'

export function ShowAlertThresholdLinesFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { showAlertThresholdLines } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const toggleShowAlertThresholdLines = (): void => {
        updateInsightFilter({ showAlertThresholdLines: !showAlertThresholdLines })
    }

    return (
        <DisplayOptionCheckbox
            label="Show alert threshold lines"
            checked={!!showAlertThresholdLines}
            onChange={toggleShowAlertThresholdLines}
        />
    )
}
