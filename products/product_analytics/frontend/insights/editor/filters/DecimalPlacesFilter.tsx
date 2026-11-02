import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { ChartOptionNumberInput } from 'lib/components/ChartOptions/ChartOptionNumberInput'
import { DEFAULT_DECIMAL_PLACES } from 'lib/utils/numbers'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function DecimalPlacesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <ChartOptionNumberInput
            label="Decimal places"
            value={trendsFilter?.decimalPlaces}
            min={0}
            max={9}
            placeholder={String(DEFAULT_DECIMAL_PLACES)}
            onChange={(decimalPlaces) => {
                updateInsightFilter({ decimalPlaces })
                posthog.capture('decimal places changed', { decimal_places: decimalPlaces })
            }}
        />
    )
}
