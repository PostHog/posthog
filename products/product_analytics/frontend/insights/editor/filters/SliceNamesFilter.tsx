import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { DisplayOptionCheckbox } from 'products/product_analytics/frontend/insights/editor/DisplayOptionCheckbox'

// Pie only — it's the one display that draws the series label on the chart itself.
export function SliceNamesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { showLabelOnSeries } = useValues(insightVizDataLogic(insightProps))

    return (
        <DisplayOptionCheckbox
            label="Show names on slices"
            checked={!!showLabelOnSeries}
            onChange={() => {
                updateInsightFilter({ showLabelsOnSeries: !showLabelOnSeries })
            }}
        />
    )
}
