import { useActions, useValues } from 'kea'

import { IconGridMasonry, IconList, IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dateMapping } from 'lib/utils/dateFilters'
import { pluralize } from 'lib/utils/strings'

import { FilterPill } from '../../components/FilterPill'
import { visionScannersListLogic } from '../../logics/visionScannersListLogic'
import { SCANNER_TYPE_OPTIONS, ScannerType } from '../types'
import { type WatchFeedView, watchFeedLogic } from '../watchFeedLogic'
import { FILLER_REASON_KINDS, WatchFeedCard, WatchFeedGridCard } from './WatchFeedCard'
import { WatchFeedEmptyState } from './WatchFeedEmptyState'

const TYPE_OPTIONS: { value: ScannerType; label: string }[] = SCANNER_TYPE_OPTIONS.map(({ value, label }) => ({
    value,
    label,
}))

// The endpoint caps the window at 90 days and rejects "All time" style bounds, so offer only ranges it accepts.
const FEED_DATE_OPTION_KEYS = new Set([
    'Today',
    'Yesterday',
    'Last 24 hours',
    'Last 7 days',
    'Last 14 days',
    'Last 30 days',
    'Last 90 days',
])
const FEED_DATE_OPTIONS = dateMapping.filter((option) => FEED_DATE_OPTION_KEYS.has(option.key))

const GRID_CLASS_NAME = 'grid gap-3 grid-cols-1 @xl:grid-cols-2 @3xl:grid-cols-3'

function FeedSkeleton({ view }: { view: WatchFeedView }): JSX.Element {
    return view === 'grid' ? (
        <div className={GRID_CLASS_NAME} aria-busy>
            {[0, 1, 2].map((i) => (
                <div key={i} className="flex flex-col border rounded-lg overflow-hidden">
                    <LemonSkeleton className="aspect-video w-full rounded-none" />
                    <div className="flex flex-col gap-1.5 p-3">
                        <LemonSkeleton className="h-4 w-2/3" />
                        <LemonSkeleton className="h-3 w-full" />
                        <LemonSkeleton className="h-3 w-1/2" />
                    </div>
                </div>
            ))}
        </div>
    ) : (
        <div className="flex flex-col gap-3" aria-busy>
            {[0, 1, 2].map((i) => (
                <LemonSkeleton key={i} className="h-32 rounded" />
            ))}
        </div>
    )
}

export function WatchFeedTab(): JSX.Element {
    const {
        feedItems,
        feedItemsLoading,
        feedFailed,
        dateFrom,
        dateTo,
        scannerTypeFilter,
        scannerIdsFilter,
        tagsFilter,
        tagOptions,
        search,
        hasFeedFilters,
        emptyReason,
        view,
    } = useValues(watchFeedLogic)
    const {
        setDateRange,
        setScannerTypeFilter,
        setScannerIdsFilter,
        setTagsFilter,
        setSearch,
        clearFeedFilters,
        loadFeed,
        setView,
    } = useActions(watchFeedLogic)
    const { scanners: allScanners } = useValues(visionScannersListLogic)
    const scannerOptions = allScanners.map((scanner) => ({
        value: scanner.id,
        label: scanner.name || '(untitled)',
    }))

    const items = feedItems ?? []
    // Only the scanner picker narrows *which* scanners are in scope; the others narrow within them.
    const narrowedToScanners = scannerIdsFilter.length
    const scannerCount = new Set(items.map((item) => item.observation.scanner_id)).size
    // Every card carrying a no-evidence reason means the window produced no findings. A feed that mixes a
    // finding with padding needs no explaining, so this stays off unless the whole feed is padding.
    const onlyFiller = items.length > 0 && items.every((item) => FILLER_REASON_KINDS.has(item.reason.kind))

    return (
        <div className="@container flex flex-col gap-4">
            <div className="flex flex-wrap items-end justify-between gap-2">
                <div className="flex flex-col gap-1">
                    <h2 className="text-xl font-semibold m-0">
                        {items.length > 0 ? pluralize(items.length, 'clip') : 'What to watch'}
                    </h2>
                    <p className="text-muted text-sm m-0">
                        {narrowedToScanners > 0
                            ? `Following ${pluralize(narrowedToScanners, 'scanner')} of ${allScanners.length}. `
                            : ''}
                        {items.length > 0
                            ? `Picked from ${pluralize(scannerCount, 'scanner')} in this window. Each clip is the moment an observation cites.`
                            : 'The observations most worth a look, picked across your scanners.'}
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <LemonInput
                        type="search"
                        placeholder="Search clips..."
                        value={search}
                        onChange={setSearch}
                        prefix={<IconSearch />}
                        className="max-w-xs"
                        data-attr="vision-watch-feed-search"
                    />
                    <FilterPill<string>
                        label="Scanners"
                        dataAttr="vision-watch-feed-scanners-filter"
                        searchable
                        searchPlaceholder="Search scanners..."
                        options={scannerOptions}
                        value={scannerIdsFilter}
                        onChange={setScannerIdsFilter}
                    />
                    <FilterPill<string>
                        label="Tags"
                        dataAttr="vision-watch-feed-tags-filter"
                        searchable
                        options={tagOptions}
                        value={tagsFilter}
                        onChange={setTagsFilter}
                    />
                    <FilterPill<ScannerType>
                        label="Type"
                        dataAttr="vision-watch-feed-type-filter"
                        options={TYPE_OPTIONS}
                        value={scannerTypeFilter ? [scannerTypeFilter] : []}
                        onChange={(values) => setScannerTypeFilter(values[values.length - 1] ?? null)}
                    />
                    <DateFilter
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        dateOptions={FEED_DATE_OPTIONS}
                        showRollingRangePicker={false}
                        onChange={(from, to) => setDateRange(from ?? null, to ?? null)}
                    />
                    {hasFeedFilters && (
                        <LemonButton type="tertiary" size="small" onClick={() => clearFeedFilters()}>
                            Clear filters
                        </LemonButton>
                    )}
                    <LemonSegmentedButton<WatchFeedView>
                        size="xsmall"
                        value={view}
                        onChange={setView}
                        options={[
                            {
                                value: 'grid',
                                icon: <IconGridMasonry />,
                                tooltip: 'Thumbnails',
                                'data-attr': 'vision-watch-feed-view-grid',
                            },
                            {
                                value: 'list',
                                icon: <IconList />,
                                tooltip: 'List',
                                'data-attr': 'vision-watch-feed-view-list',
                            },
                        ]}
                    />
                </div>
            </div>

            {feedItemsLoading && feedItems === null ? (
                <FeedSkeleton view={view} />
            ) : (
                <div className="flex flex-col gap-3">
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
                            Nothing stood out in this window. These are the newest clips. Try a longer date range to see
                            more.
                        </p>
                    )}
                    {items.length > 0 ? (
                        view === 'grid' ? (
                            <div className={GRID_CLASS_NAME}>
                                {items.map((item, index) => (
                                    <WatchFeedGridCard key={item.observation.id} item={item} position={index} />
                                ))}
                            </div>
                        ) : (
                            items.map((item, index) => (
                                <WatchFeedCard key={item.observation.id} item={item} position={index} />
                            ))
                        )
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
