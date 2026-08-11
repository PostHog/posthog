import { useActions, useValues } from 'kea'

import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'

import { JourneyGrid } from './JourneyGrid'
import { journeysDataLogic } from './journeysDataLogic'

export function Journeys({ showPersonsModal = true }: { showPersonsModal?: boolean }): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { gridModel, isAnchored, theme, activeChainHighlight } = useValues(journeysDataLogic(insightProps))
    const { cardClicked, cardHovered, ribbonClicked, ribbonHovered, gridLeft } = useActions(
        journeysDataLogic(insightProps)
    )

    if (gridModel.columns.length === 0) {
        return <InsightEmptyState />
    }

    return (
        <JourneyGrid
            model={gridModel}
            isAnchored={isAnchored}
            nodeColor={theme?.['preset-1'] ?? '#000000'}
            chainHighlight={activeChainHighlight}
            // Shared and embedded views cannot open a persons modal, so the elements must not look
            // clickable or take focus as buttons there.
            onCardClick={showPersonsModal ? cardClicked : undefined}
            onCardHover={cardHovered}
            onRibbonClick={showPersonsModal ? ribbonClicked : undefined}
            onRibbonHover={ribbonHovered}
            onGridLeave={gridLeft}
        />
    )
}
