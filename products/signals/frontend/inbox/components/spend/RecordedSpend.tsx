import { Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { formatRecordedSpend, recordedSpendTooltip } from './recordedSpendFormat'

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
        <Tooltip title={recordedSpendTooltip(amount, description)}>
            <span className="tabular-nums" translate="no">
                {formatRecordedSpend(amount)}
            </span>
        </Tooltip>
    )
}
