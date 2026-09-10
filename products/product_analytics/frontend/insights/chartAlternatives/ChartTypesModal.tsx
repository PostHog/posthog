import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { ChartDisplayType } from '~/types'

import type { ChartAlternativeSelection, ChartAlternativeSource } from './chartAlternativesLogic'
import type { ChartDisplayChangeWarning, ChartDisplayOption, ChartDisplayOptionGroup } from './chartDisplayOptions'
import { ChartTypeButton } from './ChartTypeButton'

export function ChartTypesModal({
    canConfirmSelection,
    currentDisplay,
    disabledReason,
    isOpen,
    onCancelSelection,
    onClose,
    onConfirmSelection,
    onSelect,
    options,
    pendingSelection,
    recommended,
    warning,
}: {
    canConfirmSelection: boolean
    currentDisplay: ChartDisplayType
    disabledReason?: string
    isOpen: boolean
    onCancelSelection: () => void
    onClose: () => void
    onConfirmSelection: () => void
    onSelect: (display: ChartDisplayType, source: ChartAlternativeSource) => void
    options: ChartDisplayOptionGroup[]
    pendingSelection: ChartAlternativeSelection | null
    recommended: ChartDisplayOption[]
    warning: ChartDisplayChangeWarning | null
}): JSX.Element {
    const groups: { title: string; options: ChartDisplayOption[]; source: ChartAlternativeSource }[] = [
        ...(recommended.length
            ? [{ title: 'Recommended for this data', options: recommended, source: 'recommended' as const }]
            : []),
        ...options.map((group) => ({ ...group, source: 'gallery' as const })),
    ]

    return (
        <>
            <LemonModal
                isOpen={isOpen}
                onClose={onClose}
                title="Chart type"
                description="Choose how to display this Trends insight."
                width={760}
                maxWidth="calc(100vw - 2rem)"
                data-attr="chart-alternatives-gallery"
            >
                <div className="@container flex flex-col gap-4">
                    {groups.map((group) => (
                        <section key={group.title} data-attr={`chart-alternatives-group-${group.source}`}>
                            <h4 className="m-0 mb-2 text-sm font-semibold">{group.title}</h4>
                            <div className="grid grid-cols-2 @min-[36rem]:grid-cols-3 gap-2">
                                {group.options.map((option) => (
                                    <ChartTypeButton
                                        key={option.display}
                                        option={option}
                                        current={option.display === currentDisplay}
                                        disabledReason={disabledReason ?? option.disabledReason}
                                        onClick={() => onSelect(option.display, group.source)}
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
