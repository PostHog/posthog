import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import type { WatchFeedItemApi } from '../../generated/api.schemas'
import { TOP_PICKS_COUNT, watchPicksLogic } from '../watchPicksLogic'
import { WatchPickRankedCard } from './WatchPickRankedCard'
import { WatchPicksEmptyState } from './WatchPicksEmptyState'

const WATCH_PAGE_LOGIC_KEY = 'what-to-watch'
const GRID_CLASS_NAME = 'grid grid-cols-2 gap-x-4 gap-y-6 px-2 @3xl:grid-cols-3 @5xl:grid-cols-4 @6xl:grid-cols-5'

function WatchGrid({
    title,
    items,
    ranked,
    surface,
}: {
    title: string
    items: WatchFeedItemApi[]
    ranked: boolean
    surface: 'top_10' | 'more'
}): JSX.Element | null {
    if (items.length === 0) {
        return null
    }
    return (
        <section className="flex flex-col gap-3">
            <h2 className="m-0 text-base font-semibold">{title}</h2>
            <div className={GRID_CLASS_NAME}>
                {items.map((item, index) => (
                    <WatchPickRankedCard
                        key={item.observation.id}
                        item={item}
                        position={ranked ? index : TOP_PICKS_COUNT + index}
                        surface={surface}
                        rank={ranked ? index + 1 : undefined}
                    />
                ))}
            </div>
        </section>
    )
}

function WatchPageContent(): JSX.Element {
    const { picks, picksLoading, picksFailed, topPicks, moreItems } = useValues(watchPicksLogic)
    const { loadPicks } = useActions(watchPicksLogic)

    let body: JSX.Element
    if (picksLoading || (picks === null && !picksFailed)) {
        body = (
            <div className={GRID_CLASS_NAME} aria-busy>
                {[0, 1, 2, 3, 4].map((i) => (
                    <LemonSkeleton key={i} className="aspect-video w-full rounded" />
                ))}
            </div>
        )
    } else if (picksFailed) {
        body = (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: loadPicks, 'data-attr': 'vision-watch-page-retry' }}
            >
                Couldn't load what to watch.
            </LemonBanner>
        )
    } else if (topPicks.length === 0) {
        body = <WatchPicksEmptyState size="large" />
    } else {
        body = (
            <>
                <WatchGrid title="Top 10 this week" items={topPicks} ranked surface="top_10" />
                <WatchGrid title="More to watch" items={moreItems} ranked={false} surface="more" />
            </>
        )
    }

    return (
        <div className="@container flex flex-col gap-8 pb-16" data-attr="vision-watch-page">
            {body}
        </div>
    )
}

export function WatchPage(): JSX.Element {
    return (
        <BindLogic logic={watchPicksLogic} props={{ logicKey: WATCH_PAGE_LOGIC_KEY }}>
            <WatchPageContent />
        </BindLogic>
    )
}
