import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'

import { ResultCustomizationBy } from '~/queries/schema/schema-general'

import { DisplayOptionToggleGroup } from 'products/product_analytics/frontend/insights/editor/DisplayOptionToggleGroup'
import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

export function ResultCustomizationByPicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { resultCustomizationBy } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(trendsDataLogic(insightProps))

    return (
        <DisplayOptionToggleGroup
            onChange={(value) => updateInsightFilter({ resultCustomizationBy: value as ResultCustomizationBy })}
            value={resultCustomizationBy}
            options={[
                { value: ResultCustomizationBy.Value, label: 'By name' },
                { value: ResultCustomizationBy.Position, label: 'By rank' },
            ]}
        />
    )
}
