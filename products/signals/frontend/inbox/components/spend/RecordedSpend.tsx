import { Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { formatCredits } from '../../utils/credits'

export function RecordedSpend({
    amount,
    description,
}: {
    amount: number | null | undefined
    description?: string
}): JSX.Element | null {
    const enabled = useFeatureFlag('SELF_DRIVING_USAGE_DISPLAY')
    if (!enabled) {
        return null
    }
    return (
        <Tooltip
            title={[
                description,
                amount == null
                    ? 'Usage was not recorded for this activity.'
                    : 'Recorded AI credit usage, before free allowances and billing exemptions.',
            ]
                .filter(Boolean)
                .join(' ')}
        >
            <span className="tabular-nums" translate="no">
                {amount == null ? 'Not tracked' : formatCredits(amount)}
            </span>
        </Tooltip>
    )
}
