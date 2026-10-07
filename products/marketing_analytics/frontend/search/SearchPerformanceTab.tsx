import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonSegmentedButton,
    LemonSelect,
    LemonSkeleton,
} from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { SearchChannel } from './searchPerformance'
import { SearchPerformanceDetail } from './SearchPerformanceDetail'
import { searchPerformanceLogic } from './searchPerformanceLogic'
import { SearchPerformanceTable } from './SearchPerformanceTable'
import { SearchSourceSuggestions } from './SearchSourceSuggestions'

export function SearchPerformanceTab(): JSX.Element {
    const {
        dataWarehouseSources,
        dataWarehouseSourcesLoading,
        sourcesError,
        sources,
        allSearchSources,
        sourceNotices,
        readySources,
        displayMetrics,
        hasPaidSources,
        showPosition,
        canShowPosition,
        search,
        query,
        breakdown,
        channel,
        hasActiveFilters,
    } = useValues(searchPerformanceLogic)
    const { loadSources, setMetrics, setSearch, setBreakdown, setChannel, selectRow, setShowPosition, clearFilters } =
        useActions(searchPerformanceLogic)
    const loading = !sourcesError && (dataWarehouseSourcesLoading || !dataWarehouseSources)

    return (
        <div className="@container flex flex-col gap-4 pb-8" data-attr="marketing-search-performance">
            <div className="flex flex-wrap gap-2 items-center justify-between">
                <LemonSegmentedButton
                    value={breakdown}
                    onChange={setBreakdown}
                    options={[
                        { value: 'keyword', label: 'Keywords and queries' },
                        { value: 'page', label: 'Landing pages' },
                    ]}
                />
                <LemonSelect<SearchChannel>
                    value={channel}
                    onChange={setChannel}
                    options={[
                        { value: 'all', label: 'Paid and organic' },
                        { value: 'paid', label: 'Paid search' },
                        { value: 'organic', label: 'Organic search' },
                    ]}
                />
            </div>
            <div>
                <h2 className="mb-1">{breakdown === 'page' ? 'Landing page performance' : 'Search performance'}</h2>
                <p className="text-secondary mb-0">
                    {breakdown === 'page'
                        ? 'See which pages receive paid and organic search traffic. Click a page to explore its organic queries.'
                        : 'Compare ad keywords with organic search queries. Click a keyword or query to explore its landing pages.'}
                </p>
            </div>
            {loading ? (
                <LemonSkeleton repeat={5} className="h-10" />
            ) : sourcesError ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadSources, loading }}>
                    Could not load your search sources. Try again to view search performance.
                </LemonBanner>
            ) : (
                <>
                    {!hasActiveFilters && <SearchSourceSuggestions />}
                    {sourceNotices.map(({ sourceId, message }) => (
                        <LemonBanner
                            key={sourceId}
                            type="info"
                            action={{ children: 'Manage source', to: urls.dataWarehouseSource(sourceId) }}
                        >
                            {message}
                        </LemonBanner>
                    ))}
                    {sources.length === 0 && (hasActiveFilters || allSearchSources.length > 0) && (
                        <LemonBanner type="info" action={{ children: 'Clear filters', onClick: clearFilters }}>
                            No search data matches your filters. Clear the filters to see all connected search sources.
                        </LemonBanner>
                    )}
                    {readySources.length > 0 && (
                        <>
                            <div className="flex flex-wrap gap-2 justify-between">
                                <LemonInput
                                    type="search"
                                    placeholder={breakdown === 'page' ? 'Filter pages' : 'Filter keywords and queries'}
                                    value={search}
                                    onChange={setSearch}
                                    data-attr="marketing-search-keyword-filter"
                                />
                                <div className="flex flex-wrap items-center gap-3">
                                    {canShowPosition && (
                                        <LemonCheckbox
                                            checked={showPosition}
                                            onChange={setShowPosition}
                                            label="Show position"
                                            data-attr="marketing-search-show-position"
                                        />
                                    )}
                                    <LemonSegmentedButton
                                        value={displayMetrics}
                                        onChange={setMetrics}
                                        options={[
                                            { value: 'traffic', label: 'Traffic' },
                                            {
                                                value: 'conversions',
                                                label: 'Conversions',
                                                disabledReason:
                                                    !hasPaidSources && breakdown !== 'page'
                                                        ? 'Reported conversions require synced ad platform data. Check your source settings or filters. Google Search Console only reports organic traffic.'
                                                        : undefined,
                                            },
                                        ]}
                                    />
                                </div>
                            </div>
                            <SearchPerformanceTable
                                query={query}
                                metrics={displayMetrics}
                                showPosition={showPosition}
                                onSelect={selectRow}
                                emptyState={
                                    <div className="flex flex-col items-center gap-2 py-4">
                                        <span>
                                            {hasActiveFilters
                                                ? 'No search data matches your filters. Try clearing them to see more results.'
                                                : 'No search data for this period. Try a wider date range or check your source sync status.'}
                                        </span>
                                        {hasActiveFilters && (
                                            <LemonButton type="secondary" size="small" onClick={clearFilters}>
                                                Clear filters
                                            </LemonButton>
                                        )}
                                    </div>
                                }
                            />
                            <p className="text-secondary text-xs mb-0">
                                Top 100 results by clicks, grouped by platform, match type and currency.{' '}
                                {breakdown === 'keyword' &&
                                    'Paid rows show targeted keywords; organic rows show actual Google queries. '}
                                Reported conversions use the ad platform's attribution. Google Search Console does not
                                report spend or conversions, and can omit low-volume queries. Organic positions are
                                weighted by impressions. Hover over a change to see its comparison value.
                            </p>
                        </>
                    )}
                </>
            )}
            <SearchPerformanceDetail />
        </div>
    )
}
