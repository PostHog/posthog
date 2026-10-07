import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTable } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
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
import { SEARCH_PERFORMANCE_QUERY_KEY, SEARCH_PLATFORM_LABELS, SearchMetrics } from './searchPerformance'

export function SearchPerformanceTable({
    query,
    metrics,
    showPosition = false,
    emptyState = 'No results match this date range. Try a wider date range.',
    onSelect,
    queryKey = SEARCH_PERFORMANCE_QUERY_KEY,
}: {
    query: MarketingAnalyticsSearchQuery
    metrics: SearchMetrics
    showPosition?: boolean
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
    const searchResponse = response as MarketingAnalyticsSearchQueryResponse | undefined
    const rows = searchResponse?.results ?? []
    const goals = query.includePostHogConversions ? (searchResponse?.posthogConversionGoals ?? []) : []
    const hasPaidSources = query.sources.some((source) => source.sourceType !== 'GoogleSearchConsole')
    const hasOrganicSources = query.sources.some((source) => source.sourceType === 'GoogleSearchConsole')
    const metricKeys: (keyof MarketingAnalyticsSearchMetrics)[] =
        metrics === 'traffic'
            ? [
                  'clicks',
                  'impressions',
                  'ctr',
                  ...(hasPaidSources ? ['cost' as const] : []),
                  ...(hasOrganicSources && (!hasPaidSources || showPosition) ? ['position' as const] : []),
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
        <>
            {query.includePostHogConversions && !responseLoading && searchResponse && (
                <LemonBanner
                    type="info"
                    action={
                        goals.length === 0
                            ? {
                                  children: 'Configure conversion goals',
                                  to: urls.settings('environment-marketing-analytics'),
                              }
                            : undefined
                    }
                >
                    {goals.length === 0
                        ? 'Add an event or action conversion goal in Marketing analytics settings to see PostHog conversions by landing page.'
                        : `PostHog conversions use ${searchResponse.posthogAttributionMode?.replaceAll('_', ' ') ?? 'your configured'} attribution, matched by landing URL and search source. URL query parameters and fragments are combined. Organic rows have no cost per conversion.`}
                    {searchResponse.posthogConversionsWarning && (
                        <p className="mb-0 mt-1">{searchResponse.posthogConversionsWarning}</p>
                    )}
                </LemonBanner>
            )}
            <LemonTable<MarketingAnalyticsSearchRow>
                size="small"
                tableLayout="fixed"
                firstColumnSticky
                allowContentScroll
                className="[&_th]:whitespace-normal"
                dataSource={responseLoading ? [] : rows}
                loading={responseLoading}
                loadingSkeletonRows={5}
                rowKey={(row) => JSON.stringify([row.keyword, row.page, row.platform, row.matchType, row.currency])}
                pagination={{ pageSize: 10 }}
                useURLForSorting={false}
                emptyState={emptyState}
                columns={[
                    {
                        title: query.breakdown === 'page' ? 'Landing page' : 'Keyword or query',
                        key: 'keyword',
                        width: 260,
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
                                        : [SEARCH_PLATFORM_LABELS[row.platform], row.matchType, row.currency]
                                              .filter(Boolean)
                                              .join(' · ')}
                                </span>
                            </div>
                        ),
                    },
                    {
                        title: 'Platform',
                        width: 220,
                        key: 'platform',
                        render: (_, row) => (
                            <span
                                className="flex items-center gap-1 min-w-0"
                                title={SEARCH_PLATFORM_LABELS[row.platform]}
                            >
                                <SourceIcon type={row.platform} size="xsmall" disableTooltip />
                                <span className="truncate">{SEARCH_PLATFORM_LABELS[row.platform]}</span>
                            </span>
                        ),
                    },
                    ...metricKeys.map((metric) => ({
                        title: (
                            <span className="whitespace-normal">
                                {
                                    {
                                        clicks: 'Clicks',
                                        impressions: 'Impressions',
                                        ctr: 'CTR',
                                        cost: 'Cost',
                                        conversions: 'Reported conversions',
                                        cpc: 'CPC',
                                        cpa: 'Reported CPA',
                                        position: 'Position',
                                    }[metric]
                                }
                            </span>
                        ),
                        width: 200,
                        tooltip: {
                            clicks: 'Clicks reported by the search source',
                            impressions: 'Impressions reported by the search source',
                            ctr: 'Clicks divided by impressions',
                            cost: 'Spend in the ad account currency',
                            conversions: 'Conversions attributed by the ad platform',
                            cpc: 'Spend divided by clicks',
                            cpa: 'Spend divided by conversions reported by the ad platform',
                            position:
                                'Average position in organic Google search, weighted by impressions. Lower is better.',
                        }[metric],
                        key: metric,
                        align: 'right' as const,
                        sorter: (a: MarketingAnalyticsSearchRow, b: MarketingAnalyticsSearchRow) =>
                            (a[metric] ?? -1) - (b[metric] ?? -1),
                        render: (_: unknown, row: MarketingAnalyticsSearchRow) => {
                            const value = row[metric] ?? null
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
                                                  : metric === 'conversions' || metric === 'position' || money
                                                    ? 'decimal'
                                                    : 'number'
                                        }
                                        currency={currency ?? CurrencyCode.USD}
                                        reverseColors={
                                            metric === 'cost' ||
                                            metric === 'cpc' ||
                                            metric === 'cpa' ||
                                            metric === 'position'
                                        }
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
                    ...goals.flatMap((goal) =>
                        (['conversions', 'costPerConversion'] as const).map((metric) => ({
                            key: `${goal.id}-${metric}`,
                            title: (
                                <span className="whitespace-normal">
                                    {metric === 'conversions' ? goal.name : `Cost per ${goal.name}`}
                                </span>
                            ),
                            tooltip:
                                metric === 'conversions'
                                    ? 'Conversions attributed by PostHog'
                                    : 'Spend divided by PostHog conversions. Unavailable without spend or conversions.',
                            width: 220,
                            align: 'right' as const,
                            sorter: (a: MarketingAnalyticsSearchRow, b: MarketingAnalyticsSearchRow) =>
                                (a.posthogConversions?.find((value) => value.id === goal.id)?.[metric] ?? -1) -
                                (b.posthogConversions?.find((value) => value.id === goal.id)?.[metric] ?? -1),
                            render: (_: unknown, row: MarketingAnalyticsSearchRow) => {
                                const conversion = row.posthogConversions?.find((value) => value.id === goal.id)
                                const value = conversion?.[metric]
                                const money = metric === 'costPerConversion'
                                const previous = money
                                    ? conversion?.previousCostPerConversion
                                    : conversion?.previousConversions
                                const currency =
                                    row.currency && Object.values(CurrencyCode).includes(row.currency as CurrencyCode)
                                        ? (row.currency as CurrencyCode)
                                        : null
                                return (
                                    <div>
                                        <ChangeValueCell
                                            value={value == null ? null : [value, previous ?? null]}
                                            compare={!!query.compareFilter?.compare}
                                            kind={money && currency ? 'currency' : 'decimal'}
                                            currency={currency ?? CurrencyCode.USD}
                                            reverseColors={money}
                                        />
                                        {money && row.currency && (
                                            <span className="block text-xs text-secondary">{row.currency}</span>
                                        )}
                                    </div>
                                )
                            },
                        }))
                    ),
                ]}
            />
        </>
    )
}
