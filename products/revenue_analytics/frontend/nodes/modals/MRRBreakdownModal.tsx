import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { MRRBreakdownChart } from './MRRBreakdownChart'
import { mrrBreakdownModalLogic } from './mrrBreakdownModalLogic'

const LEGEND_ITEMS = [
    {
        key: 'revenue-analytics-new',
        label: 'New',
        description: 'Revenue from new customers',
    },
    {
        key: 'revenue-analytics-expansion',
        label: 'Expansion',
        description: 'Additional revenue from existing customers',
    },
    {
        key: 'revenue-analytics-contraction',
        label: 'Contraction',
        description: 'Revenue lost from existing customers due to downgrades/less usage',
    },
    {
        key: 'revenue-analytics-churn',
        label: 'Churn',
        description: 'Revenue lost from customers who cancelled/stopped using the product',
    },
] as const

function MRRLegend(): JSX.Element {
    return (
        <div>
            <p className="text-sm text-muted mb-3">
                This chart shows the breakdown of Monthly Recurring Revenue (MRR) by category:
            </p>
            <div className="grid grid-cols-2 gap-3">
                {LEGEND_ITEMS.map((item) => (
                    <div key={item.key} className="flex items-center gap-3">
                        <div
                            className="w-4 h-4 rounded-sm flex-shrink-0"
                            style={{ backgroundColor: `var(--color-${item.key})` }}
                        />
                        <div>
                            <span className="font-semibold text-primary">{item.label}:</span>
                            <span className="text-muted text-sm ml-2">{item.description}</span>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    )
}

export function MRRBreakdownModal(): JSX.Element | null {
    const { isModalOpen } = useValues(mrrBreakdownModalLogic)
    const { closeModal } = useActions(mrrBreakdownModalLogic)

    if (!isModalOpen) {
        return null
    }

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeModal}
            simple={false}
            title="MRR Breakdown"
            width={1600}
            fullScreen={false}
            closable={true}
        >
            <LemonModal.Content embedded>
                <MRRBreakdownModalContent />
            </LemonModal.Content>
        </LemonModal>
    )
}

export function MRRBreakdownModalContent(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <MRRLegend />
            <MRRBreakdownChart />
        </div>
    )
}
