import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { pluralize } from 'lib/utils/strings'

import { FilterPill } from '../../components/FilterPill'
import { visionScannersListLogic } from '../../logics/visionScannersListLogic'
import { SCANNER_TYPE_OPTIONS, ScannerType } from '../types'
import { watchFeedLogic } from '../watchFeedLogic'
import { WatchFeedCard, observationClipRange } from './WatchFeedCard'

const TYPE_OPTIONS: { value: ScannerType; label: string }[] = SCANNER_TYPE_OPTIONS.map(({ value, label }) => ({
    value,
    label,
}))

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
    } = useValues(watchFeedLogic)
    const {
        setDateRange,
        setScannerTypeFilter,
        setScannerIdsFilter,
        setTagsFilter,
        setSearch,
        clearFeedFilters,
        loadFeed,
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
    const citedMinutes = Math.round(
        items.reduce((total, item) => {
            const clip = observationClipRange(item.observation)
            return total + (clip ? Math.max(clip.endMs - clip.startMs, 30_000) : 30_000)
        }, 0) / 60_000
    )

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-end justify-between gap-2">
                <div className="flex flex-col gap-1">
                    <h2 className="text-xl font-semibold m-0">
                        {items.length > 0
                            ? `${pluralize(items.length, 'clip')}, about ${pluralize(Math.max(citedMinutes, 1), 'minute')}`
                            : 'What to watch'}
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
                        searchable
                        searchPlaceholder="Search scanners..."
                        options={scannerOptions}
                        value={scannerIdsFilter}
                        onChange={setScannerIdsFilter}
                    />
                    <FilterPill<string>
                        label="Tags"
                        searchable
                        options={tagOptions}
                        value={tagsFilter}
                        onChange={setTagsFilter}
                    />
                    <FilterPill<ScannerType>
                        label="Type"
                        options={TYPE_OPTIONS}
                        value={scannerTypeFilter ? [scannerTypeFilter] : []}
                        onChange={(values) => setScannerTypeFilter(values[values.length - 1] ?? null)}
                    />
                    <DateFilter
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        onChange={(from, to) => setDateRange(from ?? null, to ?? null)}
                    />
                    {hasFeedFilters && (
                        <LemonButton type="tertiary" size="small" onClick={() => clearFeedFilters()}>
                            Clear filters
                        </LemonButton>
                    )}
                </div>
            </div>

            {feedItemsLoading && feedItems === null ? (
                <div className="flex flex-col gap-3">
                    {[0, 1, 2].map((i) => (
                        <LemonSkeleton key={i} className="h-32 rounded" />
                    ))}
                </div>
            ) : feedFailed && feedItems === null ? (
                <div className="flex items-center gap-2 text-sm text-secondary border rounded p-4">
                    <span>Couldn't load the feed.</span>
                    <LemonButton size="small" type="secondary" onClick={() => loadFeed()}>
                        Try again
                    </LemonButton>
                </div>
            ) : items.length === 0 ? (
                <div className="flex flex-col items-center gap-2 text-sm text-secondary border border-dashed rounded p-6 text-center">
                    {hasFeedFilters ? (
                        <>
                            <span>No clips match these filters in this window.</span>
                            <LemonButton type="secondary" size="small" onClick={() => clearFeedFilters()}>
                                Clear filters
                            </LemonButton>
                        </>
                    ) : (
                        <span>
                            Nothing worth watching in this window yet. Observations appear here as your scanners run.
                        </span>
                    )}
                </div>
            ) : (
                <div className="flex flex-col gap-3">
                    {items.map((item, index) => (
                        <WatchFeedCard key={item.observation.id} item={item} position={index} />
                    ))}
                </div>
            )}
        </div>
    )
}
