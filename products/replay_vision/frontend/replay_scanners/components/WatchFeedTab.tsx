import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { useInView } from 'react-intersection-observer'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSkeleton, LemonTabs, Spinner } from '@posthog/lemon-ui'

import { isWatchFeedBlock } from '../watchFeedEmptyState'
import { FEED_DATE_OPTIONS, feedWindowOption, feedWindowPhrase, watchFeedLogic } from '../watchFeedLogic'
import { WatchFeedBlockedBanner } from './WatchFeedBlockedBanner'
import { FILLER_REASON_KINDS, WatchFeedRow } from './WatchFeedCard'
import { WatchFeedEmptyState } from './WatchFeedEmptyState'

function FeedSkeleton(): JSX.Element {
    return (
        <div className="mx-auto flex w-full max-w-xl flex-col gap-4" aria-busy>
            {[0, 1, 2].map((i) => (
                <LemonSkeleton key={i} className="h-80 rounded-lg" />
            ))}
        </div>
    )
}

/** Loads the next page as the reader nears the end, and closes the feed once the ranking runs out. */
function FeedEnd({ itemCount }: { itemCount: number }): JSX.Element | null {
    const { feedHasMore, feedItemsLoading, feedMoreFailed } = useValues(watchFeedLogic)
    const { loadMoreFeed } = useActions(watchFeedLogic)
    // Starts the request a little before the end is on screen, so a steady scroll rarely waits.
    const { ref, inView } = useInView({ rootMargin: '600px 0px' })

    useEffect(() => {
        if (inView && feedHasMore && !feedItemsLoading && !feedMoreFailed) {
            loadMoreFeed({})
        }
    }, [inView, feedHasMore, feedItemsLoading, feedMoreFailed, loadMoreFeed])

    if (feedMoreFailed) {
        return (
            <div className="flex items-center gap-2 text-sm text-secondary border rounded p-4">
                <span>Couldn't load more sessions.</span>
                <LemonButton size="small" type="secondary" onClick={() => loadMoreFeed({})}>
                    Try again
                </LemonButton>
            </div>
        )
    }
    if (feedHasMore) {
        return (
            <div ref={ref} aria-busy>
                <LemonSkeleton className="h-80 rounded-lg" />
            </div>
        )
    }
    return itemCount > 3 ? (
        <p className="text-sm text-secondary text-center m-0 py-4" data-attr="vision-watch-feed-end">
            You're caught up. New sessions show up here as your scanners find them.
        </p>
    ) : null
}

export function WatchFeedTab(): JSX.Element {
    const {
        feedItems,
        feedItemsLoading,
        feedReloading,
        feedLoad,
        feedFailed,
        dateFrom,
        scopedToMine,
        hasOwnScanners,
        emptyReason,
    } = useValues(watchFeedLogic)
    const { setDateFrom, setOnlyMyScanners, loadFeed } = useActions(watchFeedLogic)

    const items = feedItems ?? []
    // Every card carrying a no-evidence reason means the window produced no findings. A feed that mixes a
    // finding with padding needs no explaining, so this stays off unless the whole feed is padding.
    const onlyFiller = items.length > 0 && items.every((item) => FILLER_REASON_KINDS.has(item.reason.kind))

    const rangeMenu = (
        <LemonMenu
            items={FEED_DATE_OPTIONS.map((option) => ({
                label: option.label,
                active: option.value === dateFrom,
                onClick: () => setDateFrom(option.value),
            }))}
        >
            <LemonButton
                size="small"
                type="tertiary"
                sideIcon={<IconChevronDown />}
                data-attr="vision-watch-feed-range"
            >
                {feedWindowOption(dateFrom)?.label ?? dateFrom}
            </LemonButton>
        </LemonMenu>
    )

    return (
        <div className="@container flex flex-col gap-4">
            {/* The intro explains the feed on its own, and a project without scanners has no window to pick. */}
            {!(emptyReason === 'no-scanners' && items.length === 0) && (
                <div className="mx-auto flex w-full max-w-xl items-center justify-between gap-2 -mb-2">
                    <p className="text-sm text-secondary m-0">Sessions that stand out in your scanner results.</p>
                    {!hasOwnScanners && rangeMenu}
                </div>
            )}
            {hasOwnScanners && (
                <LemonTabs
                    size="small"
                    // The small size packs tabs two units apart below md, too tight for two labels this long.
                    className="mx-auto w-full max-w-xl -mb-2 [&_ul>div]:gap-x-6"
                    activeKey={scopedToMine ? 'mine' : 'all'}
                    onChange={(key) => setOnlyMyScanners(key === 'mine')}
                    data-attr="vision-watch-feed-scope"
                    tabs={[
                        { key: 'all', label: 'All scanners', 'data-attr': 'vision-watch-feed-scope-all' },
                        { key: 'mine', label: 'My scanners', 'data-attr': 'vision-watch-feed-scope-mine' },
                    ]}
                    rightSlotClassName="bg-transparent pr-0"
                    rightSlot={rangeMenu}
                />
            )}
            {/* The first render comes before the mount starts the load, and a filter change keeps the last
                result until the new one lands, so an empty screen is only drawn from a finished load. */}
            {(feedItems === null && !feedFailed) || (feedItemsLoading && items.length === 0) ? (
                <FeedSkeleton />
            ) : (
                <div className="relative mx-auto flex w-full max-w-xl flex-col gap-4">
                    {/* The last result stays while a filter change loads, dimmed so it doesn't read as the new one. */}
                    {feedReloading && (
                        <div
                            className="pointer-events-none absolute inset-0 z-10 flex justify-center pt-32"
                            data-attr="vision-watch-feed-reloading"
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
                    {items.length > 0 && isWatchFeedBlock(emptyReason) && (
                        <WatchFeedBlockedBanner reason={emptyReason} />
                    )}
                    {items.length > 0 ? (
                        <div
                            className={clsx('flex flex-col gap-4 transition-opacity', feedReloading && 'opacity-40')}
                            aria-busy={feedReloading}
                            // `inert` keeps the stale cards out of keyboard reach; React 18 types lack the attribute.
                            {...(feedReloading ? { inert: '' } : {})}
                        >
                            {/* Three newest clips and nothing else is the answer, not a half-loaded feed, so say so
                            rather than leaving the reader to infer it from three identical reason lines. */}
                            {onlyFiller && (
                                <p className="text-sm text-secondary m-0">
                                    No sessions stood out {feedWindowPhrase(dateFrom)}. These are the newest ones.
                                </p>
                            )}
                            {items.map((item, index) => (
                                <WatchFeedRow
                                    key={`${feedLoad?.feedLoadId}-${item.observation.id}`}
                                    item={item}
                                    position={index}
                                />
                            ))}
                            <FeedEnd itemCount={items.length} />
                        </div>
                    ) : feedFailed ? null : emptyReason ? (
                        <WatchFeedEmptyState reason={emptyReason} />
                    ) : (
                        // Still resolving why the feed is empty. The scanner list defaults to empty while
                        // it loads, so naming a reason now would show the no-scanners screen to a reader
                        // who has scanners.
                        <LemonSkeleton className="h-32 rounded" />
                    )}
                </div>
            )}
        </div>
    )
}
