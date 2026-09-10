import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { pluralize } from 'lib/utils/strings'

import { FilterPill } from '../../components/FilterPill'
import { SCANNER_TYPE_OPTIONS, ScannerType } from '../types'
import { watchFeedLogic } from '../watchFeedLogic'
import { WatchFeedCard, observationClipRange } from './WatchFeedCard'

const TYPE_OPTIONS: { value: ScannerType; label: string }[] = SCANNER_TYPE_OPTIONS.map(({ value, label }) => ({
    value,
    label,
}))

export function WatchFeedTab(): JSX.Element {
    const { feedItems, feedItemsLoading, feedFailed, dateFrom, dateTo, scannerTypeFilter } = useValues(watchFeedLogic)
    const { setDateRange, setScannerTypeFilter, loadFeed } = useActions(watchFeedLogic)

    const items = feedItems ?? []
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
                        {items.length > 0
                            ? `Picked from ${pluralize(scannerCount, 'scanner')} in this window. Each clip is the moment an observation cites.`
                            : 'The observations most worth a look, picked across your scanners.'}
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
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
                <div className="text-sm text-secondary border border-dashed rounded p-6 text-center">
                    Nothing worth watching in this window yet. Observations appear here as your scanners run.
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
