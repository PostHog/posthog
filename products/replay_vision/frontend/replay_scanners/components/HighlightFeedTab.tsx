import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { RefObject, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useInView } from 'react-intersection-observer'

import { LemonButton, LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import { isHighlightFeedBlock } from '../highlightFeedEmptyState'
import { feedWindowPhrase, highlightFeedLogic } from '../highlightFeedLogic'
import { HighlightFeedBlockedBanner } from './HighlightFeedBlockedBanner'
import { FILLER_REASON_KINDS, HighlightFeedRow } from './HighlightFeedCard'
import { HighlightFeedEmptyState } from './HighlightFeedEmptyState'
import { HighlightFeedHeader } from './HighlightFeedHeader'

/** Columns follow the scene's width, so cards stay a similar size and a wide window fills with them rather than empty margin. */
const FEED_GRID = 'grid grid-cols-1 items-start gap-4 @[72rem]:grid-cols-2 @[120rem]:grid-cols-3 @[176rem]:grid-cols-4'
/** A single column stays card-sized rather than stretching one poster across the whole scene. */
const FEED_WIDTH = 'mx-auto w-full max-w-3xl @[72rem]:max-w-none'

function CardSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-3 rounded-lg border bg-surface-primary p-4">
            <LemonSkeleton className="h-5 w-1/2" />
            <div className="flex flex-col gap-1.5">
                <LemonSkeleton className="h-4 w-full" />
                <LemonSkeleton className="h-4 w-3/4" />
            </div>
            <LemonSkeleton className="h-3 w-2/3" />
            <LemonSkeleton className="aspect-video w-full rounded-md" />
            <LemonSkeleton className="h-4 w-1/3" />
        </div>
    )
}

function FeedSkeleton(): JSX.Element {
    return (
        <div className={clsx(FEED_WIDTH, FEED_GRID)} aria-busy>
            {[0, 1, 2, 3].map((i) => (
                <CardSkeleton key={i} />
            ))}
        </div>
    )
}

/** Reads the column count the grid's container queries chose; call it from inside the grid so it remounts with it. */
function useGridColumns(grid: RefObject<HTMLElement>): number {
    const [columns, setColumns] = useState(1)
    // Measured before paint, so the first frame already shows the right number of placeholders.
    useLayoutEffect(() => {
        const element = grid.current
        if (!element) {
            return
        }
        const measure = (): void =>
            setColumns(Math.max(1, getComputedStyle(element).gridTemplateColumns.split(' ').filter(Boolean).length))
        measure()
        const observer = new ResizeObserver(measure)
        observer.observe(element)
        return () => observer.disconnect()
    }, [grid])
    return columns
}

/** Loads the next page as the reader nears the end, and closes the feed once the ranking runs out. */
function FeedEnd({ itemCount, grid }: { itemCount: number; grid: RefObject<HTMLElement> }): JSX.Element | null {
    const { feedHasMore, feedItemsLoading, feedMoreFailed } = useValues(highlightFeedLogic)
    const columns = useGridColumns(grid)
    const { loadMoreFeed } = useActions(highlightFeedLogic)
    // Starts the request a little before the end is on screen, so a steady scroll rarely waits.
    const { ref, inView } = useInView({ rootMargin: '600px 0px' })

    useEffect(() => {
        if (inView && feedHasMore && !feedItemsLoading && !feedMoreFailed) {
            loadMoreFeed({})
        }
    }, [inView, feedHasMore, feedItemsLoading, feedMoreFailed, loadMoreFeed])

    if (feedMoreFailed) {
        return (
            <div className="col-span-full flex items-center gap-2 text-sm text-secondary border rounded p-4">
                <span>Couldn't load more sessions.</span>
                <LemonButton size="small" type="secondary" onClick={() => loadMoreFeed({})}>
                    Try again
                </LemonButton>
            </div>
        )
    }
    if (feedHasMore) {
        // Fills the rest of the last row, or a whole new row when it is full, where the next cards will land.
        const placeholders = columns - (itemCount % columns)
        return (
            <>
                {Array.from({ length: placeholders }, (_, index) => (
                    <div key={index} ref={index === 0 ? ref : undefined} aria-busy>
                        <CardSkeleton />
                    </div>
                ))}
            </>
        )
    }
    return itemCount > 3 ? (
        <p className="col-span-full text-sm text-secondary text-center m-0 py-4" data-attr="vision-highlight-feed-end">
            You're caught up. New sessions show up here as your scanners find them.
        </p>
    ) : null
}

export function HighlightFeedTab(): JSX.Element {
    const { feedItems, feedItemsLoading, feedReloading, feedFailed, dateFrom, emptyReason } =
        useValues(highlightFeedLogic)
    const { loadFeed } = useActions(highlightFeedLogic)
    const gridRef = useRef<HTMLDivElement>(null)

    const items = feedItems ?? []
    // Every card carrying a no-evidence reason means the window produced no findings. A feed that mixes a
    // finding with padding needs no explaining, so this stays off unless the whole feed is padding.
    const onlyFiller = items.length > 0 && items.every((item) => FILLER_REASON_KINDS.has(item.reason.kind))

    return (
        <div className="@container flex flex-col gap-4">
            {/* The empty state explains the feed on its own, and a project without scanners has nothing to filter. */}
            {!(emptyReason === 'no-scanners' && items.length === 0) && <HighlightFeedHeader className={FEED_WIDTH} />}
            {/* The first render comes before the mount starts the load, and a filter change keeps the last
                result until the new one lands, so an empty screen is only drawn from a finished load. */}
            {(feedItems === null && !feedFailed) || (feedItemsLoading && items.length === 0) ? (
                <FeedSkeleton />
            ) : (
                <div className={clsx(FEED_WIDTH, 'relative flex flex-col gap-4')}>
                    {/* The last result stays while a filter change loads, dimmed so it doesn't read as the new one. */}
                    {feedReloading && (
                        <div
                            className="pointer-events-none absolute inset-0 z-10 flex justify-center pt-32"
                            data-attr="vision-highlight-feed-reloading"
                            role="status"
                            aria-label="Loading the feed"
                        >
                            <Spinner className="sticky top-1/3 text-6xl" />
                        </div>
                    )}
                    {/* kea-loaders keeps the last value on failure, so a later filter or date change can fail
                        with cards still on screen. Show the error above them rather than replacing them. */}
                    {feedFailed && (
                        <div className="flex items-center gap-2 text-sm text-secondary border rounded p-4">
                            <span>
                                {items.length > 0
                                    ? "Couldn't refresh the feed. Showing the last results."
                                    : "Couldn't load the feed."}
                            </span>
                            <LemonButton size="small" type="secondary" onClick={() => loadFeed()}>
                                Try again
                            </LemonButton>
                        </div>
                    )}
                    {items.length > 0 && isHighlightFeedBlock(emptyReason) && (
                        <HighlightFeedBlockedBanner reason={emptyReason} />
                    )}
                    {items.length > 0 ? (
                        <div
                            ref={gridRef}
                            className={clsx(FEED_GRID, 'transition-opacity', feedReloading && 'opacity-40')}
                            aria-busy={feedReloading}
                            // `inert` keeps the stale cards out of keyboard reach; React 18 types lack the attribute.
                            {...(feedReloading ? { inert: '' } : {})}
                        >
                            {/* Three newest clips and nothing else is the answer, not a half-loaded feed, so say so
                            rather than leaving the reader to infer it from three identical reason lines. */}
                            {onlyFiller && (
                                <p className="col-span-full text-sm text-secondary m-0">
                                    No sessions stood out {feedWindowPhrase(dateFrom)}. These are the newest ones.
                                </p>
                            )}
                            {items.map((item, index) => (
                                // Keyed by the observation alone, so a card that stays across a reload keeps its loaded poster.
                                <HighlightFeedRow key={item.observation.id} item={item} position={index} />
                            ))}
                            <FeedEnd itemCount={items.length} grid={gridRef} />
                        </div>
                    ) : feedFailed ? null : emptyReason ? (
                        <div className="mx-auto w-full max-w-xl">
                            <HighlightFeedEmptyState reason={emptyReason} />
                        </div>
                    ) : (
                        // Still resolving why the feed is empty. The scanner list defaults to empty while
                        // it loads, so naming a reason now would show the no-scanners screen to a reader
                        // who has scanners.
                        <LemonSkeleton className="mx-auto h-32 w-full max-w-xl rounded" />
                    )}
                </div>
            )}
        </div>
    )
}
