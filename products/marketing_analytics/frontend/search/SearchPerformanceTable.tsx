import './SearchPerformanceTable.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton, LemonTable } from '@posthog/lemon-ui'

import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { ElapsedTime } from '~/queries/nodes/DataNode/ElapsedTime'
import { Reload } from '~/queries/nodes/DataNode/Reload'
import {
    CurrencyCode,
    MarketingAnalyticsSearchMetrics,
    MarketingAnalyticsSearchQuery,
    MarketingAnalyticsSearchQueryResponse,
    MarketingAnalyticsSearchRow,
} from '~/queries/schema/schema-general'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { MarketingQueryError } from '../dashboard/MarketingQueryError'
import { ChangeValueCell } from '../dashboard/tables/ChangeValueCell'
import { SEARCH_PLATFORM_LABELS, SearchMetrics } from './searchPerformance'
import { SearchPositionCell } from './SearchPositionCell'

export function SearchPerformanceTable({
    query,
    metrics,
    emptyState = 'No results match this date range. Try a wider date range.',
    onSelect,
    queryKey = 'marketing-search-performance',
}: {
    query: MarketingAnalyticsSearchQuery
    metrics: SearchMetrics
    emptyState?: React.ReactNode
    onSelect?: (row: MarketingAnalyticsSearchRow) => void
    queryKey?: string
}): JSX.Element {
    const logic = dataNodeLogic({
        query,
        key: queryKey,
        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })
    const { response, responseLoading, responseError, responseErrorObject, queryId } = useValues(logic)
    const { loadData } = useActions(logic)
    const rows = (response as MarketingAnalyticsSearchQueryResponse | undefined)?.results ?? []
    const hasPaidSources = query.sources.some((source) => source.sourceType !== 'GoogleSearchConsole')
    const hasPositionSources = query.sources.some((source) =>
        ['GoogleSearchConsole', 'GoogleAds', 'BingAds'].includes(source.sourceType)
    )
    const metricKeys: Exclude<
        keyof MarketingAnalyticsSearchMetrics,
        'topImpressionRate' | 'absoluteTopImpressionRate'
    >[] =
        metrics === 'traffic'
            ? [
                  'clicks',
                  'impressions',
                  'ctr',
                  ...(hasPaidSources ? ['cost' as const] : []),
                  ...(hasPositionSources ? ['position' as const] : []),
              ]
            : ['cost', 'conversions', 'cpc', 'cpa']

    if (responseError && !responseLoading) {
        return (
            <MarketingQueryError
                message="Could not load search performance. Try again or check your source's sync status."
                queryId={responseErrorObject?.queryId ?? queryId}
                onRetry={() => loadData('force_async')}
                loading={responseLoading}
            />
        )
    }
    return (
        <BindLogic logic={dataNodeLogic} props={logic.props}>
            <div className="flex flex-wrap items-center gap-2 py-2">
                <Reload />
                <ElapsedTime />
            </div>
            <LemonTable<MarketingAnalyticsSearchRow>
                size="small"
                tableLayout="fixed"
                className={clsx(
                    'SearchPerformanceTable @max-[40rem]:[&_col:nth-child(2)]:w-10 @max-[40rem]:[&_th]:px-2 @max-[40rem]:[&_td]:px-2 @max-[40rem]:[&_th_svg]:hidden @max-[40rem]:[&_.sorting-indicator]:hidden',
                    { 'SearchPerformanceTable--paginated': rows.length > 10 }
                )}
                dataSource={responseLoading ? [] : rows}
                loading={responseLoading}
                loadingSkeletonRows={10}
                rowKey={(row) => JSON.stringify([row.keyword, row.page, row.platform, row.matchType, row.currency])}
                key={JSON.stringify(query)}
                pagination={{ pageSize: 10, useUrl: false, showPageSelector: true }}
                scrollToTopOnPageChange={false}
                useURLForSorting={false}
                emptyState={emptyState}
                columns={[
                    {
                        title: query.breakdown === 'page' ? 'Landing page' : 'Keyword or query',
                        key: 'keyword',
                        width: '24%',
                        render: (_, row) => (
                            <div className="min-w-0">
                                {onSelect && (row.page || row.keyword) ? (
                                    <LemonButton type="tertiary" size="xsmall" noPadding onClick={() => onSelect(row)}>
                                        <span
                                            className="block truncate text-link"
                                            title={row.page ?? row.keyword ?? ''}
                                        >
                                            {row.page ?? row.keyword}
                                        </span>
                                    </LemonButton>
                                ) : (
                                    <span
                                        className="block truncate"
                                        title={row.page ?? row.keyword ?? 'Keyword unavailable'}
                                    >
                                        {row.page ?? row.keyword ?? 'Keyword unavailable'}
                                    </span>
                                )}
                                <span className="text-xs text-secondary block truncate">
                                    {row.platform === 'GoogleSearchConsole'
                                        ? 'Organic search'
                                        : [row.matchType, row.currency].filter(Boolean).join(' · ')}
                                </span>
                            </div>
                        ),
                    },
                    {
                        title: <span className="SearchPerformanceTable @max-[40rem]:sr-only">Platform</span>,
                        key: 'platform',
                        render: (_, row) => (
                            <span
                                className="flex items-center gap-1 min-w-0"
                                title={SEARCH_PLATFORM_LABELS[row.platform]}
                            >
                                <SourceIcon type={row.platform} size="xsmall" disableTooltip />
                                <span className="hidden @min-[40rem]:inline truncate">
                                    {SEARCH_PLATFORM_LABELS[row.platform]}
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
                                            cost: 'Cost',
                                            conversions: 'Conversions',
                                            cpc: 'CPC',
                                            cpa: 'CPA',
                                            position: 'Position',
                                        }[metric]
                                    }
                                </span>
                                <span className="@min-[40rem]:hidden">
                                    {
                                        {
                                            clicks: 'Clicks',
                                            impressions: 'Impr.',
                                            ctr: 'CTR',
                                            cost: 'Cost',
                                            conversions: 'Conv.',
                                            cpc: 'CPC',
                                            cpa: 'CPA',
                                            position: 'Pos.',
                                        }[metric]
                                    }
                                </span>
                            </span>
                        ),
                        tooltip: {
                            clicks: 'Clicks reported by the search source',
                            impressions: 'Impressions reported by the search source',
                            ctr: 'Clicks divided by impressions',
                            cost: 'Spend in the ad account currency',
                            conversions: 'Conversions attributed by the ad platform',
                            cpc: 'Spend divided by clicks',
                            cpa: 'Spend divided by conversions',
                            position:
                                'Organic search position or paid search top and first-position impression percentages. Hover over a value for details.',
                        }[metric],
                        key: metric,
                        align: 'right' as const,
                        sorter:
                            metric === 'position' && hasPaidSources
                                ? undefined
                                : (a: MarketingAnalyticsSearchRow, b: MarketingAnalyticsSearchRow) =>
                                      (a[metric] ?? -1) - (b[metric] ?? -1),
                        render: (_: unknown, row: MarketingAnalyticsSearchRow) => {
                            if (metric === 'position') {
                                return <SearchPositionCell row={row} compare={!!query.compareFilter?.compare} />
                            }
                            const value = row[metric] ?? null
                            const money = metric === 'cost' || metric === 'cpc' || metric === 'cpa'
                            const currency =
                                row.currency && Object.values(CurrencyCode).includes(row.currency as CurrencyCode)
                                    ? (row.currency as CurrencyCode)
                                    : null
                            return (
                                <div className="SearchPerformanceTable__metric">
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
                                        reverseColors={metric === 'cost' || metric === 'cpc' || metric === 'cpa'}
                                    />
                                    {money && row.platform !== 'GoogleSearchConsole' && (
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
        </BindLogic>
    )
}
