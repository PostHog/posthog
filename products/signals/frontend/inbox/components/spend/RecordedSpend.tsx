import { Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

const currency = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
})

export function RecordedSpend({
    amount,
    description,
}: {
    amount: number | null | undefined
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
                amount == null
                    ? 'Usage was not recorded for this activity.'
                    : 'Recorded usage in USD, before credits and billing exemptions.',
            ]
                .filter(Boolean)
                .join(' ')}
        >
            <span className="tabular-nums" translate="no">
                {amount == null ? 'Not tracked' : currency.format(amount / 100)}
            </span>
        </Tooltip>
    )
}
