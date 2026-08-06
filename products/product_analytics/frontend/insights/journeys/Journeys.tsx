import { useValues } from 'kea'

import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'

import { JourneyGrid } from './JourneyGrid'
import { journeysDataLogic } from './journeysDataLogic'

export function Journeys(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { gridModel, isAnchored, theme } = useValues(journeysDataLogic(insightProps))

    if (gridModel.columns.length === 0) {
        return <InsightEmptyState />
    }

    return <JourneyGrid model={gridModel} isAnchored={isAnchored} nodeColor={theme?.['preset-1'] ?? '#000000'} />
}
