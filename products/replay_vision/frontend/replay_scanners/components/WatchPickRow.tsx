import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { ObservationThumbnail } from '../../components/ObservationThumbnail'
import type { WatchFeedItemApi } from '../../generated/api.schemas'
import { type WatchPickSurface, watchPicksLogic } from '../watchPicksLogic'
import { watchPickSummary } from '../watchPickSummary'
import { watchReasonCopy } from './WatchFeedCard'
import { WatchPickRankBadge } from './WatchPickRankBadge'

interface WatchPickRowProps {
    item: WatchFeedItemApi
    position: number
    surface: WatchPickSurface
    isActive: boolean
    rank?: number
}

export function WatchPickRow({ item, position, surface, isActive, rank }: WatchPickRowProps): JSX.Element {
    const { watchPick } = useActions(watchPicksLogic)
    const { observation, reason } = item
    const { title, scannerName, person } = watchPickSummary(observation)

    return (
        <LemonButton
            fullWidth
            size="small"
            active={isActive}
            onClick={() => watchPick(item, position, surface)}
            tooltip={
                <div className="flex w-64 flex-col gap-1.5 py-1">
                    <ObservationThumbnail observation={observation} className="w-full" />
                    <span className="text-sm font-semibold leading-tight">{title}</span>
                    <span className="text-xs">
                        {person} · {scannerName}
                    </span>
                    <span className="text-xs">{watchReasonCopy(reason)}</span>
                </div>
            }
            tooltipPlacement="right"
            className="min-w-0"
            data-attr="vision-watch-pick"
        >
            <span className="flex w-full min-w-0 items-center gap-3 py-1">
                <span className="relative w-32 shrink-0">
                    <ObservationThumbnail observation={observation} className="w-full" />
                    {rank !== undefined && <WatchPickRankBadge rank={rank} />}
                </span>
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="truncate text-sm font-semibold">{title}</span>
                    <span className="truncate text-xs font-normal text-secondary">
                        <span>{scannerName}</span>
                        <span> · </span>
                        <TZLabel time={observation.created_at} />
                    </span>
                    <span className="truncate text-xs font-normal text-secondary">{watchReasonCopy(reason)}</span>
                </span>
            </span>
        </LemonButton>
    )
}
