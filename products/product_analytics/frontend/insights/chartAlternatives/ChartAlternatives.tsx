import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import type { InsightLogicProps } from '~/types'

import { chartAlternativesLogic } from './chartAlternativesLogic'
import { ChartTypeButton } from './ChartTypeButton'
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
        canReturn,
        canShowAlternatives,
        currentDisplay,
        galleryOpen,
        options,
        pendingSelection,
        selectionDisabledReason,
        warning,
    } = useValues(logic)
    const { clearPendingSelection, closeGallery, confirmSelection, openGallery, returnToOriginal, selectChart } =
        useActions(logic)

    if (!canShowAlternatives) {
        return null
    }

    return (
        <div className="@container border-b px-2 py-2" data-attr="chart-alternatives">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs font-semibold text-secondary">Chart type</span>
                <div className="flex min-w-0 flex-wrap items-center gap-1">
                    {canReturn ? (
                        <LemonButton
                            size="small"
                            type="tertiary"
                            data-attr="chart-alternatives-return"
                            onClick={returnToOriginal}
                        >
                            Return to original
                        </LemonButton>
                    ) : null}
                    <ChartTypesModal
                        canConfirmSelection={canConfirmSelection}
                        currentDisplay={currentDisplay}
                        disabledReason={selectionDisabledReason}
                        galleryOpen={galleryOpen}
                        options={options}
                        pendingSelection={pendingSelection}
                        warning={warning}
                        onCancelSelection={clearPendingSelection}
                        onCloseGallery={closeGallery}
                        onConfirmSelection={confirmSelection}
                        onSelect={(display) => selectChart(display, 'gallery')}
                        onShowGallery={openGallery}
                    />
                </div>
            </div>
            <div className="grid grid-cols-2 gap-2 @min-[44rem]:grid-cols-4">
                {alternatives.map((option) => (
                    <ChartTypeButton
                        key={option.display}
                        compact
                        option={option}
                        current={option.display === currentDisplay}
                        disabledReason={selectionDisabledReason ?? option.disabledReason}
                        onClick={() => selectChart(option.display, 'strip')}
                    />
                ))}
            </div>
        </div>
    )
}
