import { useActions } from 'kea'

import { IconPlayFilled } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'

import { ObservationThumbnail } from '../../components/ObservationThumbnail'
import { ScannerTypeBadge, scannerTypeIcon } from '../../components/ScannerTypeBadge'
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
    const play = (): void => watchPick(item, position, surface)

    return (
        <div className="group relative flex flex-col gap-1.5" data-attr="vision-watch-ranked-card">
            <div className="relative overflow-hidden rounded">
                <LemonButton noPadding fullWidth onClick={play} data-attr="vision-watch-ranked-poster">
                    <ObservationThumbnail observation={observation} className="w-full rounded-none border-0">
                        <span className="sr-only">{title}</span>
                    </ObservationThumbnail>
                </LemonButton>
                {rank !== undefined && <WatchPickRankBadge rank={rank} />}
                {signalsCount > 0 && (
                    <span className="pointer-events-none absolute bottom-2 left-2 rounded bg-black/80 px-1.5 text-xxs font-semibold text-white">
                        {signalsCount} {signalsCount === 1 ? 'signal' : 'signals'}
                    </span>
                )}
            </div>
            <div
                className={cn(
                    'pointer-events-none absolute inset-x-0 top-0 z-20 origin-top scale-95 opacity-0',
                    'overflow-hidden rounded border bg-bg-light shadow-lg transition motion-reduce:transition-none',
                    'group-hover:pointer-events-auto group-hover:scale-105 group-hover:opacity-100',
                    'group-focus-within:pointer-events-auto group-focus-within:scale-105 group-focus-within:opacity-100'
                )}
            >
                <ObservationThumbnail observation={observation} className="w-full rounded-none border-0" />
                <div className="flex flex-col gap-1.5 p-3">
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconPlayFilled />}
                            onClick={play}
                            data-attr="vision-watch-ranked-play"
                        >
                            Watch now
                        </LemonButton>
                        {scannerType && <ScannerTypeBadge scannerType={scannerType} size="small" />}
                    </div>
                    <span className="text-sm font-semibold leading-tight">{title}</span>
                    <span className="truncate text-xs text-secondary">{scannerName}</span>
                    <span className="text-xs text-secondary">{watchReasonCopy(reason)}</span>
                </div>
            </div>
            <div className="flex gap-2">
                {scannerType && (
                    <LemonTag
                        type={SCANNER_TYPE_TAG_TYPE[scannerType]}
                        className="h-7 w-7 shrink-0 justify-center rounded-full p-0 text-sm"
                        title={scannerName}
                    >
                        {scannerTypeIcon(scannerType)}
                    </LemonTag>
                )}
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="truncate text-sm font-semibold">{title}</span>
                    <span className="truncate text-xs text-secondary">
                        <span>{scannerName}</span>
                        <span> · </span>
                        <TZLabel time={observation.created_at} />
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
                            <span className="ml-1 text-xxs text-secondary">{notability.toFixed(2)}</span>
                        </span>
                    )}
                </div>
            </div>
        </div>
    )
}
