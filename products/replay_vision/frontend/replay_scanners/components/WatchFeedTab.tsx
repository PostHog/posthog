import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { useInView } from 'react-intersection-observer'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSkeleton, LemonTabs } from '@posthog/lemon-ui'

import { watchFeedLogic } from '../watchFeedLogic'
import { FILLER_REASON_KINDS, WatchFeedRow } from './WatchFeedCard'
import { WatchFeedEmptyState } from './WatchFeedEmptyState'

const FEED_DATE_OPTIONS = [
    { value: '-24h', label: 'Last 24 hours' },
    { value: '-7d', label: 'Last 7 days' },
    { value: '-30d', label: 'Last 30 days' },
    { value: '-90d', label: 'Last 90 days' },
]

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
    const { feedItems, feedItemsLoading, feedLoad, feedFailed, dateFrom, onlyMyScanners, emptyReason } =
        useValues(watchFeedLogic)
    const { setDateFrom, setOnlyMyScanners, loadFeed } = useActions(watchFeedLogic)

    const items = feedItems ?? []
    // Every card carrying a no-evidence reason means the window produced no findings. A feed that mixes a
    // finding with padding needs no explaining, so this stays off unless the whole feed is padding.
    const onlyFiller = items.length > 0 && items.every((item) => FILLER_REASON_KINDS.has(item.reason.kind))

    return (
        <div className="@container flex flex-col gap-4">
            <p className="mx-auto w-full max-w-xl text-sm text-secondary m-0 -mb-2">
                Sessions that stand out in your scanner results.
            </p>
            <LemonTabs
                size="small"
                // The small size packs tabs two units apart below md, too tight for two labels this long.
                className="mx-auto w-full max-w-xl -mb-2 [&_ul>div]:gap-x-6"
                activeKey={onlyMyScanners ? 'mine' : 'all'}
                onChange={(key) => setOnlyMyScanners(key === 'mine')}
                data-attr="vision-watch-feed-scope"
                tabs={[
                    { key: 'all', label: 'All scanners', 'data-attr': 'vision-watch-feed-scope-all' },
                    { key: 'mine', label: 'My scanners', 'data-attr': 'vision-watch-feed-scope-mine' },
                ]}
                rightSlotClassName="bg-transparent pr-0"
                rightSlot={
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
                            {FEED_DATE_OPTIONS.find((option) => option.value === dateFrom)?.label ?? dateFrom}
                        </LemonButton>
                    </LemonMenu>
                }
            />
            {feedItemsLoading && feedItems === null ? (
                <FeedSkeleton />
            ) : (
                <div className="mx-auto flex w-full max-w-xl flex-col gap-4">
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
                    {/* Three newest clips and nothing else is the answer, not a half-loaded feed, so say so
                        rather than leaving the reader to infer it from three identical reason lines. */}
                    {onlyFiller && (
                        <p className="text-sm text-secondary m-0">
                            Nothing stood out in this window. These are the newest sessions. Try a longer date range to
                            see more.
                        </p>
                    )}
                    {items.length > 0 ? (
                        <>
                            {items.map((item, index) => (
                                <WatchFeedRow
                                    key={`${feedLoad?.feedLoadId}-${item.observation.id}`}
                                    item={item}
                                    position={index}
                                />
                            ))}
                            <FeedEnd itemCount={items.length} />
                        </>
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
