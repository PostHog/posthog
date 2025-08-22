import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { MRRBreakdownChart } from './MRRBreakdownChart'
import { mrrBreakdownModalLogic } from './mrrBreakdownModalLogic'

interface MRRLegendItem {
    key: string
    label: string
    description: string
}

const legendItems: MRRLegendItem[] = [
    {
        key: 'new',
        label: 'New',
        description: 'Revenue from new customers',
    },
    {
        key: 'expansion',
        label: 'Expansion',
        description: 'Additional revenue from existing customers',
    },
    {
        key: 'contraction',
        label: 'Contraction',
        description: 'Revenue lost from existing customers due to downgrades/less usage',
    },
    {
        key: 'churn',
        label: 'Churn',
        description: 'Revenue lost from customers who cancelled/stopped using the product',
    },
]

function MRRLegend(): JSX.Element {
    return (
        <div>
            <p className="text-sm text-muted mb-3">
                This chart shows the breakdown of Monthly Recurring Revenue (MRR) by category:
            </p>
            <div className="grid grid-cols-2 gap-3">
                {legendItems.map((item) => (
                    <div key={item.key} className="flex items-center gap-3">
                        <div
                            className="w-4 h-4 rounded-sm flex-shrink-0"
                            style={{ backgroundColor: `var(--revenue-analytics-revenue-${item.key})` }}
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
    const { featureFlags } = useValues(featureFlagLogic)

    if (!isModalOpen || !featureFlags[FEATURE_FLAGS.MRR_BREAKDOWN_REVENUE_ANALYTICS]) {
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
                <div className="flex flex-col gap-4">
                    <MRRLegend />
                    <MRRBreakdownChart />
                </div>
            </LemonModal.Content>
        </LemonModal>
    )
}
