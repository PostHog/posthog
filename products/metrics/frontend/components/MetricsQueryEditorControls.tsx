import { useValues } from 'kea'

import { MetricsQueryControls, type MetricsQueryControlsProps } from './MetricsQueryControls'
import { metricsViewerLogic } from './metricsViewerLogic'

/** The editor's controls. With `allPanels`, also offers the heatmap while the query can draw one. */
export function MetricsQueryEditorControls({
    allPanels,
    ...props
}: Pick<
    MetricsQueryControlsProps,
    'dataAttrPrefix' | 'fallbackQuery' | 'onSwitchLanguage' | 'onRerun' | 'allPanels'
>): JSX.Element {
    const { heatmapEligible } = useValues(metricsViewerLogic)
    return (
        <MetricsQueryControls
            {...props}
            allPanels={allPanels}
            heatmap={allPanels ? { eligible: heatmapEligible } : undefined}
        />
    )
}
