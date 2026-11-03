import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonMenu,
    LemonSwitch,
    LemonSegmentedButton,
    LemonSelect,
    LemonSkeleton,
} from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { SourceSetupPanel } from '../dashboard/SourceSetupPanel'
import { SearchBreakdown, SearchChannel } from './searchPerformance'
import { SearchPerformanceDetail } from './SearchPerformanceDetail'
import { searchPerformanceLogic } from './searchPerformanceLogic'
import { SearchPerformanceTable } from './SearchPerformanceTable'
import { SearchSourceSuggestions } from './SearchSourceSuggestions'

export function SearchPerformanceTab({
    showSourceSuggestions = true,
}: {
    showSourceSuggestions?: boolean
}): JSX.Element {
    const {
        dataWarehouseSources,
        dataWarehouseSourcesLoading,
        sourcesError,
        sources,
        allSearchSources,
        sourceNotices,
        readySources,
        displayMetrics,
        wrapText,
        conversionsDisabledReason,
        search,
        query,
        breakdown,
        channel,
        hasActiveFilters,
        enablingSourceIds,
    } = useValues(searchPerformanceLogic)
    const {
        loadSources,
        setMetrics,
        setSearch,
        setBreakdown,
        setChannel,
        selectRow,
        clearFilters,
        setWrapText,
        enableSearchTermTables,
    } = useActions(searchPerformanceLogic)
    const loading = !sourcesError && !dataWarehouseSources
    const sourceIssues = sourceNotices.filter(({ kind }) => kind !== 'info')
    const sourceInfoNotices = sourceNotices.filter(({ kind }) => kind === 'info')

    return (
        <div className="@container flex flex-col gap-4 pb-8" data-attr="marketing-search-performance">
            <div>
                <h2 className="mb-1">
                    {breakdown === 'page'
                        ? 'Landing page performance'
                        : breakdown === 'search_term'
                          ? 'Search term performance'
                          : 'Search performance'}
                </h2>
                <p className="text-secondary mb-0">
                    {breakdown === 'page'
                        ? 'See which pages receive paid and organic search traffic. Click a page to explore its organic queries.'
                        : breakdown === 'search_term'
                          ? 'Compare the searches that triggered your Google Ads with organic search queries. Click a term to explore its organic landing pages.'
                          : 'Compare ad keywords with organic search queries. Click a keyword or query to explore its landing pages.'}
                </p>
            </div>
            <div className="flex flex-wrap gap-2 items-center justify-between">
                <LemonSegmentedButton<SearchBreakdown>
                    value={breakdown}
                    onChange={setBreakdown}
                    options={[
                        { value: 'keyword', label: 'Keywords and queries' },
                        { value: 'search_term', label: 'Search terms' },
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
            {loading ? (
                <LemonSkeleton repeat={5} className="h-10" />
            ) : sourcesError && !dataWarehouseSources ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadSources, loading: dataWarehouseSourcesLoading }}
                >
                    Could not load your search sources. Try again to view search performance.
                </LemonBanner>
            ) : (
                <>
                    {showSourceSuggestions && !hasActiveFilters && <SearchSourceSuggestions />}
                    {sourceIssues.length > 0 && (
                        <SourceSetupPanel
                            state="waiting"
                            compact
                            title={
                                breakdown === 'search_term'
                                    ? "Some search term tables aren't ready"
                                    : "Some search tables aren't ready"
                            }
                            description={
                                sourceIssues.some(({ kind }) => kind === 'attention')
                                    ? 'Check the sources below to see all your search data.'
                                    : 'More search data will appear when the first sync finishes.'
                            }
                            showIllustration={false}
                            expansionKey="search-performance"
                            connections={sourceIssues.map(
                                ({
                                    sourceId,
                                    sourceType,
                                    name,
                                    message,
                                    kind,
                                    enableSchemaIds,
                                    enableButtonLabel,
                                }) => ({
                                    id: sourceId,
                                    name,
                                    sourceType,
                                    status: kind === 'attention' ? 'Needs attention' : 'Syncing',
                                    detail: message,
                                    action: (
                                        <div className="flex flex-wrap gap-2">
                                            {enableSchemaIds.length > 0 && (
                                                <LemonButton
                                                    type="primary"
                                                    size="small"
                                                    onClick={() => enableSearchTermTables(sourceId, enableSchemaIds)}
                                                    loading={enablingSourceIds.includes(sourceId)}
                                                    data-attr="marketing-search-enable-search-term-tables"
                                                >
                                                    {enableButtonLabel}
                                                </LemonButton>
                                            )}
                                            <LemonButton
                                                type="secondary"
                                                size="small"
                                                to={urls.dataWarehouseSource(`managed-${sourceId}`)}
                                                targetBlank
                                                data-attr="marketing-search-manage-source"
                                            >
                                                Manage source
                                            </LemonButton>
                                        </div>
                                    ),
                                })
                            )}
                        />
                    )}
                    {sourceInfoNotices.map(({ sourceId, name, message }) => (
                        <LemonBanner
                            key={sourceId}
                            type="info"
                            action={{
                                children: 'Manage source',
                                to: urls.dataWarehouseSource(`managed-${sourceId}`),
                                targetBlank: true,
                                'data-attr': 'marketing-search-manage-source',
                            }}
                        >
                            {`${name}: ${message}`}
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
                                    placeholder={
                                        breakdown === 'page'
                                            ? 'Filter pages'
                                            : breakdown === 'search_term'
                                              ? 'Filter terms'
                                              : 'Filter keywords and queries'
                                    }
                                    value={search}
                                    onChange={setSearch}
                                    data-attr="marketing-search-keyword-filter"
                                />
                                <div className="flex flex-wrap items-center gap-3">
                                    <LemonMenu
                                        items={[
                                            {
                                                custom: true,
                                                label: (
                                                    <LemonSwitch
                                                        label="Wrap text"
                                                        checked={wrapText}
                                                        onChange={setWrapText}
                                                    />
                                                ),
                                            },
                                        ]}
                                    >
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            data-attr="marketing-search-table-options"
                                        >
                                            Table options
                                        </LemonButton>
                                    </LemonMenu>
                                    <LemonSegmentedButton
                                        value={displayMetrics}
                                        onChange={setMetrics}
                                        options={[
                                            { value: 'traffic', label: 'Traffic' },
                                            {
                                                value: 'conversions',
                                                label: 'Conversions',
                                                disabledReason: conversionsDisabledReason ?? undefined,
                                            },
                                        ]}
                                    />
                                </div>
                            </div>
                            <SearchPerformanceTable
                                query={query}
                                metrics={displayMetrics}
                                wrapText={wrapText}
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
                                {breakdown === 'search_term' &&
                                    'Paid rows combine the search terms from Search and Performance Max campaigns. Google Ads can omit low-volume search terms. '}
                                Reported conversions use the ad platform's attribution. Google Search Console does not
                                report spend or conversions, and can omit queries. Organic positions are weighted by
                                impressions. Hover over a change to see its comparison value.
                            </p>
                        </>
                    )}
                </>
            )}
            <SearchPerformanceDetail />
        </div>
    )
}
