import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { watchPicksLogic } from '../watchPicksLogic'
import { WatchPickRow } from './WatchPickRow'
import { WatchPicksEmptyState } from './WatchPicksEmptyState'

const LIST_TOP_COUNT = 5

export function WatchPicksList(): JSX.Element {
    const { picks, picksLoading, picksFailed, activeSessionId } = useValues(watchPicksLogic)
    const { loadPicks } = useActions(watchPicksLogic)

    return (
        <div
            className="flex h-full w-full min-w-60 flex-col overflow-hidden rounded border bg-bg-light contain-inline-size"
            data-attr="vision-watch-picks-list"
        >
            <div className="min-h-0 flex-1 overflow-y-auto">
                {picksLoading || (picks === null && !picksFailed) ? (
                    <div className="flex flex-col gap-2 p-2" aria-busy>
                        {[0, 1, 2, 3].map((i) => (
                            <LemonSkeleton key={i} className="h-16 rounded" />
                        ))}
                    </div>
                ) : picksFailed ? (
                    <LemonBanner
                        type="error"
                        className="m-2"
                        action={{ children: 'Try again', onClick: loadPicks, 'data-attr': 'vision-watch-picks-retry' }}
                    >
                        Couldn't load what to watch.
                    </LemonBanner>
                ) : !picks || picks.length === 0 ? (
                    <WatchPicksEmptyState size="small" />
                ) : (
                    <div className="flex flex-col gap-0.5 p-1">
                        {picks.map((item, index) => (
                            <WatchPickRow
                                key={item.observation.id}
                                item={item}
                                position={index}
                                surface="list"
                                rank={index < LIST_TOP_COUNT ? index + 1 : undefined}
                                isActive={item.observation.session_id === activeSessionId}
                            />
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
