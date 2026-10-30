import { Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SpendAmountApi } from 'products/signals/frontend/generated/api.schemas'

const currency = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
})

export function RecordedSpend({
    spend,
    description,
}: {
    spend: SpendAmountApi | undefined
    description?: string
}): JSX.Element | null {
    const enabled = useFeatureFlag('SELF_DRIVING_USAGE')
    if (!enabled) {
        return null
    }
    return (
        <Tooltip
            title={[
                description,
                spend?.total_spend == null
                    ? 'Usage was not recorded for this activity.'
                    : 'Recorded usage in USD, before credits and billing exemptions.',
            ]
                .filter(Boolean)
                .join(' ')}
        >
            <span className="tabular-nums" translate="no">
                {spend?.total_spend == null ? 'Not tracked' : currency.format(spend.total_spend / 100)}
            </span>
        </Tooltip>
    )
}
