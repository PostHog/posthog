import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { ChartDisplayType } from '~/types'

import type { ChartAlternativeSelection } from './chartAlternativesLogic'
import type { ChartDisplayChangeWarning, ChartDisplayOptionGroup } from './chartDisplayOptions'
import { ChartTypeButton } from './ChartTypeButton'

export function ChartTypesModal({
    canConfirmSelection,
    currentDisplay,
    disabledReason,
    galleryOpen,
    onCancelSelection,
    onCloseGallery,
    onConfirmSelection,
    onSelect,
    onShowGallery,
    options,
    pendingSelection,
    warning,
}: {
    canConfirmSelection: boolean
    currentDisplay: ChartDisplayType
    disabledReason?: string
    galleryOpen: boolean
    onCancelSelection: () => void
    onCloseGallery: () => void
    onConfirmSelection: () => void
    onSelect: (display: ChartDisplayType) => void
    onShowGallery: () => void
    options: ChartDisplayOptionGroup[]
    pendingSelection: ChartAlternativeSelection | null
    warning: ChartDisplayChangeWarning | null
}): JSX.Element {
    return (
        <>
            <LemonButton
                size="small"
                type="secondary"
                data-attr="chart-alternatives-all"
                disabledReason={disabledReason}
                onClick={onShowGallery}
            >
                All chart types
            </LemonButton>
            <LemonModal
                isOpen={galleryOpen}
                onClose={onCloseGallery}
                title="All chart types"
                description="Choose a chart type for this Trends insight."
                width={760}
                maxWidth="calc(100vw - 2rem)"
                data-attr="chart-alternatives-gallery"
            >
                <div className="@container flex flex-col gap-4">
                    {options.map((group) => (
                        <section key={group.title}>
                            <h4 className="m-0 mb-2 text-sm font-semibold">{group.title}</h4>
                            <div className="grid grid-cols-2 @min-[36rem]:grid-cols-3 gap-2">
                                {group.options.map((option) => (
                                    <ChartTypeButton
                                        key={option.display}
                                        option={option}
                                        current={option.display === currentDisplay}
                                        disabledReason={disabledReason ?? option.disabledReason}
                                        onClick={() => onSelect(option.display)}
                                    />
                                ))}
                            </div>
                        </section>
                    ))}
                </div>
            </LemonModal>
            <LemonModal
                isOpen={!!pendingSelection}
                onClose={onCancelSelection}
                title={warning?.title ?? 'Change chart type'}
                width={440}
                maxWidth="calc(100vw - 2rem)"
                footer={
                    <div className="flex justify-end gap-2">
                        <LemonButton type="secondary" onClick={onCancelSelection}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            data-attr="chart-alternatives-confirm"
                            disabledReason={
                                !canConfirmSelection ? (disabledReason ?? 'The chart has changed.') : undefined
                            }
                            onClick={onConfirmSelection}
                        >
                            Change chart
                        </LemonButton>
                    </div>
                }
            >
                <p className="m-0">{warning?.body}</p>
            </LemonModal>
        </>
    )
}
