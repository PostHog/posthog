import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import type { InsightLogicProps } from '~/types'

import { chartAlternativesLogic } from './chartAlternativesLogic'
import { ChartDisplayIcon } from './ChartDisplayIcon'
import { ChartTypesModal } from './ChartTypesModal'

export function ChartAlternatives({
    editMode,
    embedded,
    inSharedMode,
    insightProps,
}: {
    editMode?: boolean
    embedded: boolean
    inSharedMode?: boolean
    insightProps: InsightLogicProps
}): JSX.Element | null {
    const logic = useMountedLogic(chartAlternativesLogic({ editMode, embedded, inSharedMode, ...insightProps }))
    const {
        alternatives,
        canConfirmSelection,
        canShowAlternatives,
        currentDisplay,
        currentOption,
        galleryOpen,
        options,
        pendingSelection,
        selectionDisabledReason,
        warning,
    } = useValues(logic)
    const { clearPendingSelection, closeGallery, confirmSelection, openGallery, selectChart } = useActions(logic)

    if (!canShowAlternatives) {
        return null
    }

    return (
        <span data-attr="chart-alternatives">
            <LemonButton
                size="small"
                type="secondary"
                icon={currentOption ? <ChartDisplayIcon icon={currentOption.icon} /> : undefined}
                data-attr="chart-alternatives-all"
                disabledReason={selectionDisabledReason}
                onClick={openGallery}
            >
                {currentOption?.label ?? 'Chart type'}
            </LemonButton>
            <ChartTypesModal
                canConfirmSelection={canConfirmSelection}
                currentDisplay={currentDisplay}
                disabledReason={selectionDisabledReason}
                isOpen={galleryOpen}
                options={options}
                pendingSelection={pendingSelection}
                recommended={alternatives}
                warning={warning}
                onCancelSelection={clearPendingSelection}
                onClose={closeGallery}
                onConfirmSelection={confirmSelection}
                onSelect={selectChart}
            />
        </span>
    )
}
