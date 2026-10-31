import { useActions, useValues } from 'kea'

import { LegendOption, LegendPosition } from 'lib/components/ChartOptions/LegendOption'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function LegendOptionsFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showLegend, legendPosition } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const position = (legendPosition ?? (showLegend ? 'right' : 'bottom')) as LegendPosition

    return (
        <LegendOption
            showLegend={!!showLegend}
            onShowLegendChange={(checked) =>
                updateInsightFilter({
                    showLegend: checked,
                    // Seed bottom on first enable — old insights without a saved position render right (chart-config fallback).
                    ...(checked && legendPosition == null ? { legendPosition: 'bottom' } : {}),
                })
            }
            position={position}
            onPositionChange={(position) => updateInsightFilter({ legendPosition: position })}
        />
    )
}
