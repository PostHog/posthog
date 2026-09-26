import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { urls } from 'scenes/urls'
import { IntegrationFilter } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsFilters/IntegrationFilter'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { ReloadAll } from '~/queries/nodes/DataNode/Reload'

import { SEARCH_PLATFORM_LABELS, SEARCH_SOURCE_TYPES } from './searchPerformance'
import { searchPerformanceLogic } from './searchPerformanceLogic'
import { SearchPerformanceTable } from './SearchPerformanceTable'

export function SearchPerformanceTab(): JSX.Element {
    const {
        dataWarehouseSources,
        dataWarehouseSourcesLoading,
        sourcesError,
        sources,
        pendingSources,
        readySources,
        compareFilter,
        metrics,
        search,
        dateFilter,
        query,
    } = useValues(searchPerformanceLogic)
    const { loadSources, setMetrics, setSearch } = useActions(searchPerformanceLogic)
    const { setDates, setCompareFilter } = useActions(marketingAnalyticsLogic)
    const loading = !sourcesError && (dataWarehouseSourcesLoading || !dataWarehouseSources)

    return (
        <div className="@container flex flex-col gap-4" data-attr="marketing-search-performance">
            <div className="flex flex-wrap items-center gap-2">
                <IntegrationFilter sourceTypes={SEARCH_SOURCE_TYPES} />
                <DateFilter
                    size="small"
                    dateFrom={dateFilter.dateFrom}
                    dateTo={dateFilter.dateTo}
                    onChange={setDates}
                />
                <CompareFilter compareFilter={compareFilter} updateCompareFilter={setCompareFilter} />
                <ReloadAll />
            </div>
            <div>
                <h2 className="mb-1">Paid search keywords</h2>
                <p className="text-secondary mb-0">Compare the keywords you target in Google Ads and Bing Ads.</p>
            </div>
            {loading ? (
                <LemonSkeleton repeat={5} className="h-10" />
            ) : sourcesError ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadSources, loading }}>
                    Could not load your ad platforms. Try again to view search performance.
                </LemonBanner>
            ) : (
                <>
                    {sources.length === 0 && (
                        <div className="border rounded p-4 flex flex-col gap-3 items-start">
                            <p className="mb-0">Connect an ad platform to see keyword clicks, spend and conversions.</p>
                            <div className="flex flex-wrap gap-2">
                                <LemonButton
                                    type="primary"
                                    to={urls.dataWarehouseSourceNew(
                                        'GoogleAds',
                                        `${urls.marketingAnalyticsApp()}?tab=search-performance`,
                                        'Search performance'
                                    )}
                                    data-attr="marketing-search-connect-google"
                                >
                                    Connect Google Ads
                                </LemonButton>
                                <LemonButton
                                    type="secondary"
                                    to={urls.dataWarehouseSourceNew(
                                        'BingAds',
                                        `${urls.marketingAnalyticsApp()}?tab=search-performance`,
                                        'Search performance'
                                    )}
                                    data-attr="marketing-search-connect-bing"
                                >
                                    Connect Bing Ads
                                </LemonButton>
                            </div>
                        </div>
                    )}
                    {pendingSources.map((source) => (
                        <LemonBanner
                            key={source.id}
                            type="info"
                            action={{ children: 'Manage source', to: urls.dataWarehouseSource(source.id) }}
                        >
                            {`${source.description || SEARCH_PLATFORM_LABELS[source.source_type as 'GoogleAds' | 'BingAds']}: enable ${source.source_type === 'GoogleAds' ? 'keyword and keyword_stats' : 'keyword_performance_report'} and wait for the first sync to finish.`}
                        </LemonBanner>
                    ))}
                    {readySources.length > 0 && (
                        <>
                            <div className="flex flex-wrap gap-2 justify-between">
                                <LemonInput
                                    type="search"
                                    placeholder="Filter keywords"
                                    value={search}
                                    onChange={setSearch}
                                    data-attr="marketing-search-keyword-filter"
                                />
                                <LemonSegmentedButton
                                    value={metrics}
                                    onChange={setMetrics}
                                    options={[
                                        { value: 'traffic', label: 'Traffic' },
                                        { value: 'conversions', label: 'Spend and conversions' },
                                    ]}
                                />
                            </div>
                            <SearchPerformanceTable query={query} metrics={metrics} />
                            <p className="text-secondary text-xs mb-0">
                                Top 100 keywords by clicks. Keywords are grouped by platform, match type and account
                                currency. Comparisons show the change from the selected comparison period; hover for its
                                value. Conversions use each ad platform's attribution. These are targeted keywords;
                                people's actual searches can differ.
                            </p>
                        </>
                    )}
                </>
            )}
        </div>
    )
}
