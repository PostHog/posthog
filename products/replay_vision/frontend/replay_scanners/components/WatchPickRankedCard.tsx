import { useActions } from 'kea'

import { IconPlayFilled } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'

import { ObservationThumbnail } from '../../components/ObservationThumbnail'
import { ScannerTypeBadge, scannerTypeIcon } from '../../components/ScannerTypeBadge'
import { UnviewedObservationTag } from '../../components/UnviewedObservationTag'
import type { WatchFeedItemApi } from '../../generated/api.schemas'
import { SCANNER_TYPE_TAG_TYPE } from '../types'
import { type WatchPickSurface, watchPicksLogic } from '../watchPicksLogic'
import { watchPickSummary } from '../watchPickSummary'
import { watchReasonCopy } from './WatchFeedCard'
import { WatchPickRankBadge } from './WatchPickRankBadge'

interface WatchPickRankedCardProps {
    item: WatchFeedItemApi
    position: number
    surface: WatchPickSurface
    rank?: number
}

const SCORE_DOTS = 5

export function WatchPickRankedCard({ item, position, surface, rank }: WatchPickRankedCardProps): JSX.Element {
    const { watchPick } = useActions(watchPicksLogic)
    const { observation, reason } = item
    const { title, scannerName, scannerType } = watchPickSummary(observation)
    const signalsCount = reason.signals_count ?? 0
    const notability = typeof reason.notability === 'number' ? reason.notability : null

    return (
        <div className="group relative" data-attr="vision-watch-ranked-card">
            <LemonButton
                noPadding
                fullWidth
                onClick={() => watchPick(item, position, surface)}
                className="items-stretch"
                data-attr="vision-watch-ranked-poster"
            >
                <span className="flex w-full flex-col gap-1.5 text-left">
                    <span className={cn('relative block overflow-hidden rounded', observation.viewed && 'opacity-60')}>
                        <ObservationThumbnail observation={observation} className="w-full rounded-none border-0">
                            <span className="sr-only">{title}</span>
                        </ObservationThumbnail>
                        {rank !== undefined && <WatchPickRankBadge rank={rank} />}
                        {!observation.viewed && (
                            <UnviewedObservationTag className="pointer-events-none absolute right-2 top-2 z-10" />
                        )}
                        {signalsCount > 0 && (
                            <span className="pointer-events-none absolute bottom-2 left-2 rounded bg-black/80 px-1.5 text-xxs font-semibold text-white">
                                {signalsCount} {signalsCount === 1 ? 'signal' : 'signals'}
                            </span>
                        )}
                    </span>
                    <span className="flex gap-2">
                        {scannerType && (
                            <LemonTag
                                type={SCANNER_TYPE_TAG_TYPE[scannerType]}
                                className="h-7 w-7 shrink-0 justify-center rounded-full p-0 text-sm"
                                title={scannerName}
                            >
                                {scannerTypeIcon(scannerType)}
                            </LemonTag>
                        )}
                        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                            <span className="truncate text-sm font-semibold">{title}</span>
                            <span className="truncate text-xs font-normal text-secondary">
                                <span>{scannerName}</span>
                                <span> · </span>
                                <TZLabel time={observation.created_at} showPopover={false} noStyles />
                            </span>
                            {notability !== null && (
                                <span className="flex items-center gap-1" aria-label={`Score ${notability.toFixed(2)}`}>
                                    {Array.from({ length: SCORE_DOTS }, (_, dot) => (
                                        <span
                                            key={dot}
                                            className={cn(
                                                'h-1.5 w-1.5 rounded-full',
                                                dot < Math.round(notability * SCORE_DOTS) ? 'bg-accent' : 'bg-border'
                                            )}
                                        />
                                    ))}
                                    <span className="ml-1 text-xxs font-normal text-secondary">
                                        {notability.toFixed(2)}
                                    </span>
                                </span>
                            )}
                        </span>
                    </span>
                </span>
            </LemonButton>
            <div
                aria-hidden
                className={cn(
                    'pointer-events-none absolute inset-x-0 top-0 z-20 hidden origin-top scale-95 opacity-0 @4xl:block',
                    'overflow-hidden rounded border bg-bg-light shadow-lg transition motion-reduce:transition-none',
                    'group-hover:scale-105 group-hover:opacity-100 group-focus-within:scale-105 group-focus-within:opacity-100'
                )}
            >
                <ObservationThumbnail observation={observation} className="w-full rounded-none border-0" />
                <div className="flex flex-col gap-1.5 p-3 text-left">
                    <span className="line-clamp-2 text-sm font-semibold leading-tight">{title}</span>
                    <span className="flex min-w-0 items-center gap-1.5 text-xs text-secondary">
                        {scannerType && <ScannerTypeBadge scannerType={scannerType} size="small" />}
                        <span className="truncate">{scannerName}</span>
                        <span>·</span>
                        <TZLabel time={observation.created_at} showPopover={false} noStyles />
                    </span>
                    <span className="line-clamp-3 text-xs leading-snug text-secondary">{watchReasonCopy(reason)}</span>
                    <span className="mt-1 flex items-center gap-1 text-xs font-semibold text-accent">
                        <IconPlayFilled />
                        Watch now
                    </span>
                </div>
            </div>
        </div>
    )
}
