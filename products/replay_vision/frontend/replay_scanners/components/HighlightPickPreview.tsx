import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'

import { ObservationThumbnail } from '../../components/ObservationThumbnail'
import { ScannerTypeBadge } from '../../components/ScannerTypeBadge'
import type { HighlightFeedItemApi } from '../../generated/api.schemas'
import { citedTextToPlainText } from '../../utils/citations'
import { highlightPickSummary } from '../highlightPickSummary'
import { highlightReasonCopy } from './HighlightFeedCard'

export function HighlightPickPreview({
    item,
    className,
}: {
    item: HighlightFeedItemApi
    className?: string
}): JSX.Element {
    const { observation, reason } = item
    const { title, scannerName, scannerType } = highlightPickSummary(observation)

    return (
        <div className={cn('flex flex-col gap-1.5 py-1', className ?? 'w-64')}>
            <ObservationThumbnail observation={observation} className="w-full" />
            <span className="text-sm font-semibold leading-tight">{title}</span>
            <span className="flex min-w-0 items-center gap-1.5 text-xs">
                {scannerType && <ScannerTypeBadge scannerType={scannerType} size="small" />}
                <span className="truncate">{scannerName}</span>
                <span>·</span>
                <TZLabel time={observation.created_at} showPopover={false} noStyles className="whitespace-nowrap" />
            </span>
            <span className="text-xs leading-snug">{citedTextToPlainText(highlightReasonCopy(reason), undefined)}</span>
        </div>
    )
}
