import { useActions } from 'kea'
import { useRef } from 'react'

import { IconThumbsDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { cn } from 'lib/utils/css-classes'

import { ObservationThumbnail } from '../../components/ObservationThumbnail'
import type { WatchFeedItemApi } from '../../generated/api.schemas'
import { citedTextToPlainText } from '../../utils/citations'
import { useCardImpression } from '../useCardImpression'
import { feedDismissalMenuItems } from '../watchFeedDismissal'
import { type WatchPickSurface, watchPicksLogic } from '../watchPicksLogic'
import { watchPickSummary } from '../watchPickSummary'
import { watchFeedRowWhy } from './WatchFeedCard'
import { WatchPickPreview } from './WatchPickPreview'
import { WatchPickRankBadge } from './WatchPickRankBadge'

interface WatchPickRowProps {
    item: WatchFeedItemApi
    position: number
    surface: WatchPickSurface
    isActive: boolean
    rank?: number
}

export function WatchPickRow({ item, position, surface, isActive, rank }: WatchPickRowProps): JSX.Element {
    const { watchPick, cardSeen, dismissItem } = useActions(watchPicksLogic)
    const { observation, reason } = item
    const { title, scannerName } = watchPickSummary(observation)
    const rowRef = useRef<HTMLDivElement>(null)
    useCardImpression(rowRef, () => cardSeen(item, position))

    return (
        <div ref={rowRef} className="min-w-0">
            <LemonButton
                fullWidth
                size="small"
                active={isActive}
                onClick={() => watchPick(item, position, surface)}
                tooltip={<WatchPickPreview item={item} />}
                tooltipPlacement="right"
                className="min-w-0"
                data-attr="vision-watch-pick"
                sideAction={{
                    icon: <IconThumbsDown />,
                    tooltip: 'Not useful',
                    'aria-label': 'Not useful',
                    'data-attr': 'vision-watch-feed-dismiss',
                    dropdown: {
                        placement: 'bottom-end',
                        overlay: (
                            <LemonMenuOverlay
                                items={feedDismissalMenuItems((dismissalReason) =>
                                    dismissItem(item, position, surface, dismissalReason)
                                )}
                            />
                        ),
                    },
                }}
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
        </div>
    )
}
