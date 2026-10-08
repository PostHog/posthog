import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { CurrencyCode } from '~/queries/schema/schema-general'

import { ChangeValueCell } from '../dashboard/tables/ChangeValueCell'
import { SEARCH_PLATFORM_LABELS } from './searchPerformance'
import { searchPerformanceLogic } from './searchPerformanceLogic'
import { SearchPerformanceTable } from './SearchPerformanceTable'

export function SearchPerformanceDetail(): JSX.Element {
    const { selectedRow, detailQuery, compareFilter, hasSearchConsole } = useValues(searchPerformanceLogic)
    const { selectRow } = useActions(searchPerformanceLogic)
    const organic = selectedRow?.platform === 'GoogleSearchConsole'
    const metricKeys: ('clicks' | 'impressions' | 'ctr' | 'position' | 'conversions')[] = [
        'clicks',
        'impressions',
        'ctr',
        organic ? 'position' : 'conversions',
    ]

    return (
        <LemonModal
            isOpen={!!selectedRow}
            onClose={() => selectRow(null)}
            title={<span className="break-all">{selectedRow?.page ?? selectedRow?.keyword ?? 'Search details'}</span>}
            description={selectedRow ? SEARCH_PLATFORM_LABELS[selectedRow.platform] : undefined}
            width={900}
        >
            {selectedRow && (
                <div className="@container flex flex-col gap-4">
                    <dl className="grid grid-cols-2 @min-[40rem]:grid-cols-4 gap-4 m-0">
                        {metricKeys.map((metric) => (
                            <div key={metric}>
                                <dt className="text-secondary text-xs mb-1">
                                    {
                                        {
                                            clicks: 'Clicks',
                                            impressions: 'Impressions',
                                            ctr: 'CTR',
                                            position: 'Average position',
                                            conversions: 'Conversions',
                                        }[metric]
                                    }
                                </dt>
                                <dd className="m-0 text-lg font-semibold">
                                    <ChangeValueCell
                                        value={
                                            selectedRow[metric] == null
                                                ? null
                                                : [selectedRow[metric], selectedRow.previous?.[metric] ?? null]
                                        }
                                        compare={!!compareFilter?.compare}
                                        kind={
                                            metric === 'ctr'
                                                ? 'percentage'
                                                : metric === 'position' || metric === 'conversions'
                                                  ? 'decimal'
                                                  : 'number'
                                        }
                                        currency={CurrencyCode.USD}
                                        reverseColors={metric === 'position'}
                                    />
                                </dd>
                            </div>
                        ))}
                    </dl>
                    <div>
                        <h3 className="mb-1">
                            {selectedRow.page ? 'Organic queries for this page' : 'Organic pages for this keyword'}
                        </h3>
                        <p className="text-secondary mb-0">
                            {selectedRow.page
                                ? 'See which Google searches bring people to this page.'
                                : 'See the pages that appear in Google for this search.'}
                            {!organic &&
                                !selectedRow.page &&
                                ' Ad keywords can match different searches; these organic results are for the same text.'}
                        </p>
                    </div>
                    {detailQuery?.sources.length ? (
                        <SearchPerformanceTable
                            query={detailQuery}
                            metrics="traffic"
                            queryKey="marketing-search-detail"
                        />
                    ) : (
                        <LemonBanner type="info">
                            {hasSearchConsole
                                ? 'Enable search_analytics_by_query_page in Google Search Console to see this breakdown.'
                                : 'Connect Google Search Console to see organic queries and landing pages.'}
                        </LemonBanner>
                    )}
                    {!hasSearchConsole && (
                        <LemonButton
                            type="primary"
                            to={urls.dataWarehouseSourceNew(
                                'GoogleSearchConsole',
                                `${urls.marketingAnalyticsApp()}?tab=ad-performance`,
                                'Marketing analytics'
                            )}
                        >
                            Connect Google Search Console
                        </LemonButton>
                    )}
                    <p className="text-xs text-secondary mb-0">
                        Google can withhold low-volume queries. Query and page breakdowns may not add up to property
                        totals.
                    </p>
                </div>
            )}
        </LemonModal>
    )
}
