import { useActions, useValues } from 'kea'

import { LemonBanner, LemonTable } from '@posthog/lemon-ui'

import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    CurrencyCode,
    MarketingAnalyticsSearchQuery,
    MarketingAnalyticsSearchQueryResponse,
    MarketingAnalyticsSearchRow,
} from '~/queries/schema/schema-general'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { ChangeValueCell } from '../dashboard/tables/ChangeValueCell'
import { SEARCH_PLATFORM_LABELS, SearchMetrics } from './searchPerformance'

export function SearchPerformanceTable({
    query,
    metrics,
}: {
    query: MarketingAnalyticsSearchQuery
    metrics: SearchMetrics
}): JSX.Element {
    const logic = dataNodeLogic({
        query,
        key: 'marketing-search-performance',
        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })
    const { response, responseLoading, responseError } = useValues(logic)
    const { loadData } = useActions(logic)
    const rows = (response as MarketingAnalyticsSearchQueryResponse | undefined)?.results ?? []
    const metricKeys =
        metrics === 'traffic'
            ? (['clicks', 'impressions', 'ctr'] as const)
            : (['cost', 'conversions', 'cpc', 'cpa'] as const)

    if (responseError && !responseLoading) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadData('force_async') }}>
                Could not load keyword performance. Try again or check your ad platform's sync status.
            </LemonBanner>
        )
    }
    return (
        <LemonTable<MarketingAnalyticsSearchRow>
            size="small"
            tableLayout="fixed"
            className="@max-[40rem]:[&_th]:px-2 @max-[40rem]:[&_td]:px-2 @max-[40rem]:[&_th_svg]:hidden @max-[40rem]:[&_.sorting-indicator]:hidden"
            dataSource={responseLoading ? [] : rows}
            loading={responseLoading}
            loadingSkeletonRows={5}
            rowKey={(row) => JSON.stringify([row.keyword, row.platform, row.matchType, row.currency])}
            pagination={{ pageSize: 10 }}
            useURLForSorting={false}
            emptyState="No keywords match this date range and filter. Try a wider date range or clear the filter."
            columns={[
                {
                    title: 'Keyword',
                    key: 'keyword',
                    width: '28%',
                    render: (_, row) => (
                        <div className="min-w-0">
                            <span className="block truncate" title={row.keyword ?? 'Keyword unavailable'}>
                                {row.keyword ?? 'Keyword unavailable'}
                            </span>
                            <span className="text-xs text-secondary block truncate">
                                {`${row.matchType ?? 'Match type unavailable'} · ${row.currency ?? 'Currency unavailable'}`}
                            </span>
                        </div>
                    ),
                },
                {
                    title: 'Platform',
                    key: 'platform',
                    render: (_, row) => (
                        <span className="flex items-center gap-1 min-w-0" title={SEARCH_PLATFORM_LABELS[row.platform]}>
                            <SourceIcon type={row.platform} size="xsmall" disableTooltip />
                            <span className="hidden @min-[40rem]:inline">{SEARCH_PLATFORM_LABELS[row.platform]}</span>
                            <span className="@min-[40rem]:hidden">
                                {row.platform === 'GoogleAds' ? 'Google' : 'Bing'}
                            </span>
                        </span>
                    ),
                },
                ...metricKeys.map((metric) => ({
                    title: (
                        <span className="whitespace-normal wrap-anywhere">
                            <span className="hidden @min-[40rem]:inline">
                                {
                                    {
                                        clicks: 'Clicks',
                                        impressions: 'Impressions',
                                        ctr: 'CTR',
                                        cost: 'Spend',
                                        conversions: 'Conversions',
                                        cpc: 'CPC',
                                        cpa: 'CPA',
                                    }[metric]
                                }
                            </span>
                            <span className="@min-[40rem]:hidden">
                                {
                                    {
                                        clicks: 'Clicks',
                                        impressions: 'Impr.',
                                        ctr: 'CTR',
                                        cost: 'Spend',
                                        conversions: 'Conv.',
                                        cpc: 'CPC',
                                        cpa: 'CPA',
                                    }[metric]
                                }
                            </span>
                        </span>
                    ),
                    tooltip: {
                        clicks: 'Clicks reported by the ad platform',
                        impressions: 'Impressions reported by the ad platform',
                        ctr: 'Clicks divided by impressions',
                        cost: 'Spend in the ad account currency',
                        conversions: 'Conversions attributed by the ad platform',
                        cpc: 'Spend divided by clicks',
                        cpa: 'Spend divided by conversions',
                    }[metric],
                    key: metric,
                    align: 'right' as const,
                    sorter: (a: MarketingAnalyticsSearchRow, b: MarketingAnalyticsSearchRow) =>
                        (a[metric] ?? -1) - (b[metric] ?? -1),
                    render: (_: unknown, row: MarketingAnalyticsSearchRow) => {
                        const value = row[metric]
                        const money = metric === 'cost' || metric === 'cpc' || metric === 'cpa'
                        const currency =
                            row.currency && Object.values(CurrencyCode).includes(row.currency as CurrencyCode)
                                ? (row.currency as CurrencyCode)
                                : null
                        return (
                            <div>
                                <ChangeValueCell
                                    value={value === null ? null : [value, row.previous?.[metric] ?? null]}
                                    compare={!!query.compareFilter?.compare}
                                    kind={
                                        metric === 'ctr'
                                            ? 'percentage'
                                            : money && currency
                                              ? 'currency'
                                              : metric === 'conversions' || money
                                                ? 'decimal'
                                                : 'number'
                                    }
                                    currency={currency ?? CurrencyCode.USD}
                                    neutral={metric === 'cost' || metric === 'impressions'}
                                    reverseColors={metric === 'cpc' || metric === 'cpa'}
                                />
                                {money && (
                                    <span className="block text-xs text-secondary">
                                        {row.currency ?? 'Unknown currency'}
                                    </span>
                                )}
                            </div>
                        )
                    },
                })),
            ]}
        />
    )
}
