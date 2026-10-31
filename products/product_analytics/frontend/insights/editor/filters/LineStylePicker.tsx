import { useActions, useValues } from 'kea'

import { LineStyleOption } from 'lib/components/ChartOptions/LineStyleOption'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import type { TrendsFilter } from '~/queries/schema/schema-general'

export function LineStylePicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { insightFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    // chartStyle exists on every filter kind this picker renders for (trends, stickiness,
    // retention, funnels) — TrendsFilter stands in for the union member carrying it.
    const chartStyle = (insightFilter as TrendsFilter | undefined)?.chartStyle

    return (
        <LineStyleOption
            // Unset curve falls through to the app default, which is smooth.
            value={chartStyle?.curve || 'smooth'}
            onChange={(curve) => updateInsightFilter({ chartStyle: { ...chartStyle, curve } })}
        />
    )
}
