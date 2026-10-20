import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { useAutoMarkRead } from 'lib/components/NotificationsMenu/useAutoMarkRead'
import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'

import { ObservationThumbnail } from '../../components/ObservationThumbnail'
import type { WatchFeedItemApi } from '../../generated/api.schemas'
import { citedTextToPlainText } from '../../utils/citations'
import { CARD_SEEN_DWELL_MS } from '../watchFeedTelemetry'
import { watchPicksLogic } from '../watchPicksLogic'
import { watchPickSummary } from '../watchPickSummary'
import { watchFeedRowWhy } from './WatchFeedCard'
import { WatchPickPreview } from './WatchPickPreview'
import { WatchPickRankBadge } from './WatchPickRankBadge'

interface WatchPickRowProps {
    item: WatchFeedItemApi
    position: number
    isActive: boolean
    rank?: number
}

export function WatchPickRow({ item, position, isActive, rank }: WatchPickRowProps): JSX.Element {
    const { watchPick, cardSeen } = useActions(watchPicksLogic)
    const { observation, reason } = item
    const { title, scannerName } = watchPickSummary(observation)
    const rowRef = useAutoMarkRead(true, () => cardSeen(item, position), CARD_SEEN_DWELL_MS)

    return (
        <LemonButton
            ref={rowRef}
            fullWidth
            size="small"
            active={isActive}
            onClick={() => watchPick(item, position)}
            tooltip={<WatchPickPreview item={item} />}
            tooltipPlacement="right"
            className="min-w-0"
            data-attr="vision-watch-pick"
        >
            <span className={cn('flex w-full min-w-0 items-center gap-3 py-1', observation.viewed && 'opacity-60')}>
                <span className="relative w-28 shrink-0">
                    <ObservationThumbnail observation={observation} className="w-full" />
                    {rank !== undefined && <WatchPickRankBadge rank={rank} size="small" />}
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
                        {citedTextToPlainText(watchFeedRowWhy(reason), undefined)}
                    </span>
                </span>
            </span>
        </LemonButton>
    )
}
