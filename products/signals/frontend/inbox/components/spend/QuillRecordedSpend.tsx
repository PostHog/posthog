import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { formatRecordedSpend, recordedSpendTooltip } from './recordedSpendFormat'

/** The quill sibling of `RecordedSpend`, for the report page behind `today-rail-nav`. */
export function QuillRecordedSpend({
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
        <Tooltip>
            <TooltipTrigger render={<span className="tabular-nums" translate="no" />}>
                {formatRecordedSpend(amount)}
            </TooltipTrigger>
            <TooltipContent>{recordedSpendTooltip(amount, description)}</TooltipContent>
        </Tooltip>
    )
}
