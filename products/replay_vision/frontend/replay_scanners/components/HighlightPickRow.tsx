import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { useAutoMarkRead } from 'lib/components/NotificationsMenu/useAutoMarkRead'
import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'

import { ObservationThumbnail } from '../../components/ObservationThumbnail'
import type { HighlightFeedItemApi } from '../../generated/api.schemas'
import { citedTextToPlainText } from '../../utils/citations'
import { CARD_SEEN_DWELL_MS } from '../highlightFeedTelemetry'
import { highlightPicksLogic } from '../highlightPicksLogic'
import { highlightPickSummary } from '../highlightPickSummary'
import { highlightReasonCopy } from './HighlightFeedCard'
import { HighlightPickPreview } from './HighlightPickPreview'
import { HighlightPickRankBadge } from './HighlightPickRankBadge'

interface HighlightPickRowProps {
    item: HighlightFeedItemApi
    position: number
    isActive: boolean
    rank?: number
}

export function HighlightPickRow({ item, position, isActive, rank }: HighlightPickRowProps): JSX.Element {
    const { highlightPick, cardSeen } = useActions(highlightPicksLogic)
    const { picksLoad } = useValues(highlightPicksLogic)
    const { observation, reason } = item
    const { title, scannerName } = highlightPickSummary(observation)
    const rowRef = useAutoMarkRead(true, () => cardSeen(item, position), CARD_SEEN_DWELL_MS, picksLoad?.feedLoadId)

    return (
        <LemonButton
            ref={rowRef}
            fullWidth
            size="small"
            active={isActive}
            onClick={() => highlightPick(item, position)}
            tooltip={<HighlightPickPreview item={item} />}
            tooltipPlacement="right"
            className="min-w-0"
            data-attr="vision-highlight-pick"
        >
            <span className={cn('flex w-full min-w-0 items-center gap-3 py-1', observation.viewed && 'opacity-60')}>
                <span className="relative w-28 shrink-0">
                    <ObservationThumbnail
                        observation={observation}
                        className="w-full"
                        size="small"
                        retryKey={picksLoad?.feedLoadId}
                    />
                    {rank !== undefined && <HighlightPickRankBadge rank={rank} size="small" />}
                    {!observation.viewed && (
                        <span className="absolute inset-y-0 left-0 w-1 rounded-l bg-accent" aria-hidden />
                    )}
                </span>
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="truncate text-sm font-semibold">
                        {!observation.viewed && <span className="sr-only">New: </span>}
                        {title}
                    </span>
                    <span className="truncate text-xs font-normal text-secondary">
                        <span>{scannerName}</span>
                        <span> · </span>
                        <TZLabel
                            time={observation.created_at}
                            showPopover={false}
                            noStyles
                            className="whitespace-nowrap"
                        />
                    </span>
                    <span className="truncate text-xs font-normal text-secondary">
                        {citedTextToPlainText(highlightReasonCopy(reason), undefined)}
                    </span>
                </span>
            </span>
        </LemonButton>
    )
}
