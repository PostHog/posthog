import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useInView } from 'react-intersection-observer'

import { LemonButton, LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import { inStorybookTestRunner } from 'lib/utils/dom'
import { teamLogic } from 'scenes/teamLogic'

import { observationThumbnailSrc, preloadObservationThumbnail } from '../../components/ObservationThumbnail'
import { HighlightFeedItemApi } from '../../generated/api.schemas'
import { isHighlightFeedBlock } from '../highlightFeedEmptyState'
import { FEED_PAGE_SIZE, feedWindowPhrase, highlightFeedLogic } from '../highlightFeedLogic'
import { HighlightFeedBlockedBanner } from './HighlightFeedBlockedBanner'
import { FILLER_REASON_KINDS, HighlightFeedRow } from './HighlightFeedCard'
import { HighlightFeedEmptyState } from './HighlightFeedEmptyState'
import { HighlightFeedHeader } from './HighlightFeedHeader'

/** Columns follow the scene's width, so cards stay a similar size and a wide window fills with them rather than empty margin. */
const FEED_GRID = 'grid grid-cols-1 items-start gap-4 @[72rem]:grid-cols-2 @[120rem]:grid-cols-3 @[176rem]:grid-cols-4'
/** A single column stays card-sized rather than stretching one poster across the whole scene. */
const FEED_WIDTH = 'mx-auto w-full max-w-3xl @[72rem]:max-w-none'

const POSTER_WAIT_CAP_MS = 10000
const SKIP_POSTER_WAIT = inStorybookTestRunner()

/** The cards whose posters are ready, so a card never shows an empty poster frame. */
function useRevealedItems(
    items: HighlightFeedItemApi[],
    feedLoadId: string | undefined
): { visible: HighlightFeedItemApi[]; pendingCount: number; holding: boolean } {
    const { currentTeamId } = useValues(teamLogic)
    const [revealed, setRevealed] = useState<Set<string>>(() => new Set())
    const [revealedLoadId, setRevealedLoadId] = useState<string | undefined>(undefined)
    const lastShown = useRef<HighlightFeedItemApi[]>([])
    // Each card's cap runs from when it first waited, so a re-run of the effect doesn't restart it.
    const deadlines = useRef(new Map<string, number>())
    const pendingItems = items.filter((item) => !revealed.has(item.observation.id))
    const pendingKey = pendingItems.map((item) => item.observation.id).join(',')
    // A filter change keeps the last result on screen until the new result's posters are ready.
    const holding = revealedLoadId !== undefined && feedLoadId !== revealedLoadId

    useEffect(() => {
        const reveal = (batch: HighlightFeedItemApi[]): void => {
            setRevealed((previous) => new Set([...previous, ...batch.map((item) => item.observation.id)]))
            setRevealedLoadId(feedLoadId)
        }
        if (pendingItems.length === 0) {
            reveal(pendingItems)
            return
        }
        // Each card shows once its own poster is ready, in feed order, so no gap opens above a slow poster.
        let cancelled = false
        let revealedUpTo = 0
        const ready = pendingItems.map(() => false)
        const timers: ReturnType<typeof setTimeout>[] = []
        pendingItems.forEach((item, index) => {
            const src = observationThumbnailSrc(currentTeamId, item.observation)
            const id = item.observation.id
            if (!deadlines.current.has(id)) {
                deadlines.current.set(id, Date.now() + POSTER_WAIT_CAP_MS)
            }
            const waitMs = Math.max(0, (deadlines.current.get(id) ?? 0) - Date.now())
            void Promise.race([
                src ? preloadObservationThumbnail(src) : Promise.resolve(),
                new Promise((resolve) => timers.push(setTimeout(resolve, waitMs))),
            ]).then(() => {
                ready[index] = true
                let end = revealedUpTo
                while (end < ready.length && ready[end]) {
                    end++
                }
                if (!cancelled && end > revealedUpTo) {
                    reveal(pendingItems.slice(revealedUpTo, end))
                    revealedUpTo = end
                }
            })
        })
        return () => {
            cancelled = true
            timers.forEach(clearTimeout)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [pendingKey, feedLoadId])

    // Cut at the first card still waiting, so a card kept from the last result can't show above a new one and shift later.
    const firstPending = items.findIndex((item) => !revealed.has(item.observation.id))
    // Snapshots wait for images on their own, and a capture mid-reveal would show a partial feed.
    const visible = SKIP_POSTER_WAIT
        ? items
        : holding
          ? lastShown.current
          : firstPending === -1
            ? items
            : items.slice(0, firstPending)
    lastShown.current = visible
    return { visible, pendingCount: SKIP_POSTER_WAIT ? 0 : pendingItems.length, holding: !SKIP_POSTER_WAIT && holding }
}

/** Reads the column count the grid's container queries chose. */
function useGridColumns(element: HTMLElement | null): number {
    const [columns, setColumns] = useState(1)
    // Measured before paint, so the first frame already staggers each row correctly.
    useLayoutEffect(() => {
        if (!element) {
            return
        }
        const measure = (): void =>
            setColumns(Math.max(1, getComputedStyle(element).gridTemplateColumns.split(' ').filter(Boolean).length))
        measure()
        const observer = new ResizeObserver(measure)
        observer.observe(element)
        return () => observer.disconnect()
    }, [element])
    return columns
}

/** Loads the next page as the reader nears the end, and closes the feed once the ranking runs out. */
function FeedEnd({ itemCount, pendingCount }: { itemCount: number; pendingCount: number }): JSX.Element | null {
    const { feedHasMore, feedItemsLoading, feedMoreFailed } = useValues(highlightFeedLogic)
    const { loadMoreFeed } = useActions(highlightFeedLogic)
    // Starts the request well before the end is on screen, so a steady scroll rarely reaches the spinner.
    const { ref, inView } = useInView({ rootMargin: '4000px 0px' })

    useEffect(() => {
        // Cards waiting on posters keep the end in place, so stop at one page ahead rather than chain requests.
        if (inView && feedHasMore && !feedItemsLoading && !feedMoreFailed && pendingCount < FEED_PAGE_SIZE) {
            loadMoreFeed({})
        }
    }, [inView, feedHasMore, feedItemsLoading, feedMoreFailed, pendingCount, loadMoreFeed])

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
    if (feedHasMore || pendingCount > 0) {
        return (
            <div ref={ref} className="col-span-full flex h-16 items-center justify-center" aria-busy>
                <Spinner className="text-2xl text-secondary" />
            </div>
        )
    }
    return itemCount > 3 ? (
        <p className="col-span-full text-sm text-secondary text-center m-0 py-4" data-attr="vision-highlight-feed-end">
            You're caught up. New sessions show up here as your scanners find them.
        </p>
    ) : null
}

export function HighlightFeedTab(): JSX.Element {
    const { feedItems, feedItemsLoading, feedReloading, feedFailed, dateFrom, emptyReason, feedLoad } =
        useValues(highlightFeedLogic)
    const { loadFeed } = useActions(highlightFeedLogic)
    // A callback ref, because a child's layout effect runs before React attaches the parent's object ref.
    const [grid, setGrid] = useState<HTMLDivElement | null>(null)

    const allItems = feedItems ?? []
    const { visible: items, pendingCount, holding } = useRevealedItems(allItems, feedLoad?.feedLoadId)
    const dimmed = feedReloading || holding
    const columns = useGridColumns(grid)
    const firstReveal = items.length === 0 && allItems.length > 0
    // Every card carrying a no-evidence reason means the window produced no findings. A feed that mixes a
    // finding with padding needs no explaining, so this stays off unless the whole feed is padding.
    const onlyFiller = items.length > 0 && items.every((item) => FILLER_REASON_KINDS.has(item.reason.kind))

    return (
        <div className="@container flex flex-col gap-4">
            {/* The empty state explains the feed on its own, and a project without scanners has nothing to filter. */}
            {!(emptyReason === 'no-scanners' && items.length === 0) && <HighlightFeedHeader className={FEED_WIDTH} />}
            {/* The first render comes before the mount starts the load, and a filter change keeps the last
                result until the new one lands, so an empty screen is only drawn from a finished load. */}
            {(feedItems === null && !feedFailed) || (feedItemsLoading && items.length === 0) || firstReveal ? (
                <div className="flex justify-center py-32" role="status" aria-label="Loading the feed">
                    <Spinner className="text-4xl text-secondary" />
                </div>
            ) : (
                <div className={clsx(FEED_WIDTH, 'relative flex flex-col gap-4')}>
                    {/* The last result stays while a filter change loads, dimmed so it doesn't read as the new one. */}
                    {dimmed && (
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
                            ref={setGrid}
                            className={clsx(FEED_GRID, 'transition-opacity', dimmed && 'opacity-40')}
                            aria-busy={dimmed}
                            // `inert` keeps the stale cards out of keyboard reach; React 18 types lack the attribute.
                            {...(dimmed ? { inert: '' } : {})}
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
                                <HighlightFeedRow
                                    key={item.observation.id}
                                    item={item}
                                    position={index}
                                    columnIndex={index % columns}
                                    stale={dimmed}
                                />
                            ))}
                            <FeedEnd itemCount={items.length} pendingCount={pendingCount} />
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
