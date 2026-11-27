import './SearchPerformanceTable.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner, LemonSkeleton, LemonTable, Link, Spinner } from '@posthog/lemon-ui'
import { Button, Skeleton, Spinner as QuillSpinner, Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { ElapsedTime } from '~/queries/nodes/DataNode/ElapsedTime'
import { Reload } from '~/queries/nodes/DataNode/Reload'
import {
    CurrencyCode,
    MarketingAnalyticsSearchMetrics,
    MarketingAnalyticsSearchQuery,
    MarketingAnalyticsSearchRow,
} from '~/queries/schema/schema-general'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { MarketingQueryError } from '../dashboard/MarketingQueryError'
import { ChangeValueCell } from '../dashboard/tables/ChangeValueCell'
import { QuillSearchNotice } from './QuillSearchNotice'
import { QuillSearchPerformanceTable, SearchPerformanceColumn } from './QuillSearchPerformanceTable'
import {
    SEARCH_PERFORMANCE_QUERY_KEY,
    SEARCH_PLATFORM_LABELS,
    SearchMetrics,
    searchPerformanceRowKey,
} from './searchPerformance'
import { searchPerformanceTableLogic } from './searchPerformanceTableLogic'
import { SearchPositionCell } from './SearchPositionCell'

type SearchMetricKey = Exclude<keyof MarketingAnalyticsSearchMetrics, 'topImpressionRate' | 'absoluteTopImpressionRate'>

const METRIC_TITLES: Record<SearchMetricKey, string> = {
    clicks: 'Clicks',
    impressions: 'Impressions',
    ctr: 'CTR',
    cost: 'Cost',
    conversions: 'Reported conversions',
    cpc: 'CPC',
    cpa: 'Reported CPA',
    position: 'Position',
}

const METRIC_TOOLTIPS: Record<SearchMetricKey, string> = {
    clicks: 'Clicks reported by the search source',
    impressions: 'Impressions reported by the search source',
    ctr: 'Clicks divided by impressions',
    cost: 'Spend in the ad account currency',
    conversions: 'Conversions attributed by the ad platform',
    cpc: 'Spend divided by clicks',
    cpa: 'Spend divided by conversions reported by the ad platform',
    position:
        'Organic search position or paid search top and first-position impression percentages. Hover over a value for details.',
}

const PLACEMENT_UNAVAILABLE_MESSAGE =
    'Some Google Ads position data is unavailable. Check your access to keyword_placement_stats or ask a project admin for help. Traffic data is available.'

const rowCurrency = (row: MarketingAnalyticsSearchRow): CurrencyCode | null =>
    row.currency && Object.values(CurrencyCode).includes(row.currency as CurrencyCode)
        ? (row.currency as CurrencyCode)
        : null

export function SearchPerformanceTable({
    query,
    metrics,
    wrapText = false,
    emptyState = 'No results match this date range. Try a wider date range.',
    onSelect,
    queryKey = SEARCH_PERFORMANCE_QUERY_KEY,
    embedded = false,
}: {
    query: MarketingAnalyticsSearchQuery
    metrics: SearchMetrics
    wrapText?: boolean
    emptyState?: React.ReactNode
    onSelect?: (row: MarketingAnalyticsSearchRow) => void
    queryKey?: string
    embedded?: boolean
}): JSX.Element {
    const logic = searchPerformanceTableLogic({ query, queryKey })
    const {
        searchResponse,
        responseLoading,
        responseError,
        responseErrorObject,
        queryId,
        baseDataNodeProps,
        rows,
        goals,
        conversionsLoading,
        conversionsError,
        conversionsErrorObject,
        conversionsQueryId,
        conversionsResponse,
    } = useValues(logic)
    const { loadData, loadConversions } = useActions(logic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const columns = useMemo<SearchPerformanceColumn[]>(() => {
        const hasPaidSources = query.sources.some((source) => source.sourceType !== 'GoogleSearchConsole')
        const hasPositionSources = query.sources.some((source) =>
            ['GoogleSearchConsole', 'GoogleAds', 'BingAds'].includes(source.sourceType)
        )
        const metricKeys: SearchMetricKey[] =
            metrics === 'traffic'
                ? [
                      'clicks',
                      'impressions',
                      'ctr',
                      ...(hasPaidSources ? ['cost' as const] : []),
                      ...(hasPositionSources ? ['position' as const] : []),
                  ]
                : ['cost', 'conversions', 'cpc', 'cpa']
        const compare = !!query.compareFilter?.compare
        const secondaryText = todayRailNav ? 'text-muted-foreground' : 'text-secondary'
        const rowSource = (row: MarketingAnalyticsSearchRow): string =>
            row.platform === 'GoogleSearchConsole'
                ? 'Organic search'
                : [SEARCH_PLATFORM_LABELS[row.platform], row.matchType, row.currency].filter(Boolean).join(' · ')

        return [
            {
                title:
                    query.breakdown === 'page'
                        ? 'Landing page'
                        : query.breakdown === 'search_term'
                          ? 'Search term or query'
                          : 'Keyword or query',
                key: 'keyword',
                width: 260,
                render: (row) =>
                    todayRailNav ? (
                        <div className="flex w-60 flex-col items-start">
                            {onSelect && (row.page || row.keyword) ? (
                                <Button
                                    variant="link-foreground"
                                    size={wrapText ? 'inline' : 'sm'}
                                    left
                                    // The table only pulls a cell's direct-child Button back into line with the header.
                                    className={clsx('max-w-full shrink', !wrapText && '-ms-2')}
                                    onClick={() => onSelect(row)}
                                    title={row.page ?? row.keyword ?? ''}
                                >
                                    <span
                                        className={wrapText ? 'text-start whitespace-normal wrap-anywhere' : 'truncate'}
                                    >
                                        {row.page ?? row.keyword}
                                    </span>
                                </Button>
                            ) : (
                                <span
                                    className={clsx(
                                        'block max-w-full',
                                        wrapText ? 'whitespace-normal wrap-anywhere' : 'truncate'
                                    )}
                                    title={row.page ?? row.keyword ?? 'Keyword unavailable'}
                                >
                                    {row.page ?? row.keyword ?? 'Keyword unavailable'}
                                </span>
                            )}
                            <span className="block max-w-full truncate text-xs text-muted-foreground">
                                {rowSource(row)}
                            </span>
                        </div>
                    ) : (
                        <div className="min-w-0">
                            {onSelect && (row.page || row.keyword) ? (
                                <Link
                                    onClick={() => onSelect(row)}
                                    className={clsx(
                                        'block max-w-full hover:underline',
                                        wrapText ? 'whitespace-normal [overflow-wrap:anywhere]' : 'truncate'
                                    )}
                                    title={row.page ?? row.keyword ?? ''}
                                >
                                    {row.page ?? row.keyword}
                                </Link>
                            ) : (
                                <span
                                    className={clsx(
                                        'block',
                                        wrapText ? 'whitespace-normal [overflow-wrap:anywhere]' : 'truncate'
                                    )}
                                    title={row.page ?? row.keyword ?? 'Keyword unavailable'}
                                >
                                    {row.page ?? row.keyword ?? 'Keyword unavailable'}
                                </span>
                            )}
                            <span className="text-xs text-secondary block truncate">{rowSource(row)}</span>
                        </div>
                    ),
            },
            {
                title: 'Platform',
                width: 220,
                key: 'platform',
                render: (row) => (
                    <span className="flex items-center gap-1 min-w-0" title={SEARCH_PLATFORM_LABELS[row.platform]}>
                        <SourceIcon type={row.platform} size="xsmall" disableTooltip />
                        <span className="truncate">{SEARCH_PLATFORM_LABELS[row.platform]}</span>
                    </span>
                ),
            },
            ...metricKeys.map(
                (metric): SearchPerformanceColumn => ({
                    title: METRIC_TITLES[metric],
                    width: 200,
                    tooltip: METRIC_TOOLTIPS[metric],
                    key: metric,
                    numeric: true,
                    sortValue: metric === 'position' && hasPaidSources ? undefined : (row) => row[metric] ?? -1,
                    render: (row) => {
                        if (metric === 'position') {
                            return <SearchPositionCell row={row} compare={compare} />
                        }
                        const value = row[metric] ?? null
                        const money = metric === 'cost' || metric === 'cpc' || metric === 'cpa'
                        const currency = rowCurrency(row)
                        return (
                            <div className="SearchPerformanceTable__metric">
                                <ChangeValueCell
                                    value={value === null ? null : [value, row.previous?.[metric] ?? null]}
                                    compare={compare}
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
                                    <span className={clsx('block text-xs', secondaryText)}>
                                        {row.currency ?? 'Unknown currency'}
                                    </span>
                                )}
                            </div>
                        )
                    },
                })
            ),
            ...goals.flatMap((goal) =>
                (['conversions', 'costPerConversion'] as const).map(
                    (metric): SearchPerformanceColumn => ({
                        key: `${goal.id}-${metric}`,
                        title: metric === 'conversions' ? goal.name : `Cost per ${goal.name}`,
                        tooltip:
                            metric === 'conversions'
                                ? 'Conversions attributed by PostHog'
                                : 'Spend divided by PostHog conversions. Unavailable without spend or conversions.',
                        width: 220,
                        numeric: true,
                        sortValue: (row) =>
                            row.posthogConversions?.find((value) => value.id === goal.id)?.[metric] ?? -1,
                        render: (row) => {
                            if (conversionsLoading) {
                                return todayRailNav ? (
                                    <Skeleton className="ml-auto h-4 w-16" />
                                ) : (
                                    <LemonSkeleton className="h-4 w-16 ml-auto" />
                                )
                            }
                            const conversion = row.posthogConversions?.find((value) => value.id === goal.id)
                            const value = conversion?.[metric]
                            const money = metric === 'costPerConversion'
                            const previous = money
                                ? conversion?.previousCostPerConversion
                                : conversion?.previousConversions
                            const currency = rowCurrency(row)
                            return (
                                <div className="SearchPerformanceTable__metric">
                                    <ChangeValueCell
                                        value={value == null ? null : [value, previous ?? null]}
                                        compare={compare}
                                        kind={money && currency ? 'currency' : 'decimal'}
                                        currency={currency ?? CurrencyCode.USD}
                                        reverseColors={money}
                                    />
                                    {money && row.currency && (
                                        <span className={clsx('block text-xs', secondaryText)}>{row.currency}</span>
                                    )}
                                </div>
                            )
                        },
                    })
                )
            ),
        ]
    }, [query, metrics, wrapText, onSelect, goals, conversionsLoading, todayRailNav])

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

    const conversionsMessage =
        goals.length === 0
            ? 'Add an event or action conversion goal in Marketing analytics settings to see PostHog conversions.'
            : `PostHog conversions use ${conversionsResponse?.posthogAttributionMode?.replaceAll('_', ' ') ?? 'your configured'} attribution. ${
                  query.breakdown === 'page'
                      ? 'Conversions are matched by landing URL and search source. URL query parameters and fragments are combined. Organic rows have no cost per conversion.'
                      : 'Paid keywords are matched to the session’s utm_term and search source. Set utm_term to the keyword in your ad links. Organic query conversions are only available by landing page.'
              }`

    return (
        <BindLogic logic={dataNodeLogic} props={baseDataNodeProps}>
            <div className="flex flex-wrap items-center gap-2 py-2">
                <Reload />
                <ElapsedTime />
            </div>
            {query.includePostHogConversions &&
                !responseLoading &&
                searchResponse &&
                (conversionsLoading ? (
                    todayRailNav ? (
                        <div className="flex items-center gap-2 py-2" role="status">
                            <QuillSpinner aria-hidden />
                            <Text size="xs" variant="muted" render={<span className="m-0" />}>
                                Loading PostHog conversions…
                            </Text>
                        </div>
                    ) : (
                        <div className="flex items-center gap-2 py-2 text-secondary" role="status">
                            <Spinner className="text-xl" />
                            <span>Loading PostHog conversions…</span>
                        </div>
                    )
                ) : conversionsError ? (
                    <MarketingQueryError
                        message="Could not load PostHog conversions. Your search data is still available."
                        queryId={conversionsErrorObject?.queryId ?? conversionsQueryId}
                        onRetry={() => loadConversions('force_async')}
                        loading={conversionsLoading}
                    />
                ) : conversionsResponse ? (
                    todayRailNav ? (
                        <QuillSearchNotice
                            action={
                                goals.length === 0 ? (
                                    <Button
                                        variant="outline"
                                        nativeButton={false}
                                        render={<LinkPrimitive to={urls.settings('environment-marketing-analytics')} />}
                                    >
                                        Configure conversion goals
                                    </Button>
                                ) : undefined
                            }
                        >
                            {conversionsMessage}
                            {conversionsResponse.posthogConversionsWarning && (
                                <span className="mt-1 block">{conversionsResponse.posthogConversionsWarning}</span>
                            )}
                        </QuillSearchNotice>
                    ) : (
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
                            {conversionsMessage}
                            {conversionsResponse.posthogConversionsWarning && (
                                <p className="mb-0 mt-1">{conversionsResponse.posthogConversionsWarning}</p>
                            )}
                        </LemonBanner>
                    )
                ) : null)}
            {!responseLoading &&
                searchResponse?.placementUnavailable &&
                (todayRailNav ? (
                    <QuillSearchNotice>{PLACEMENT_UNAVAILABLE_MESSAGE}</QuillSearchNotice>
                ) : (
                    <LemonBanner type="info">{PLACEMENT_UNAVAILABLE_MESSAGE}</LemonBanner>
                ))}
            {todayRailNav ? (
                <QuillSearchPerformanceTable
                    key={JSON.stringify(query)}
                    columns={columns}
                    rows={rows}
                    loading={responseLoading}
                    emptyState={emptyState}
                />
            ) : (
                <LemonTable<MarketingAnalyticsSearchRow>
                    size="small"
                    tableLayout="fixed"
                    firstColumnSticky
                    allowContentScroll
                    embedded={embedded}
                    className={clsx('SearchPerformanceTable [&_th]:whitespace-normal', {
                        'SearchPerformanceTable--paginated': rows.length > 10,
                        'SearchPerformanceTable--wrap-text': wrapText,
                    })}
                    dataSource={responseLoading ? [] : rows}
                    loading={responseLoading}
                    loadingSkeletonRows={10}
                    rowKey={searchPerformanceRowKey}
                    key={JSON.stringify(query)}
                    pagination={{ pageSize: 10, useUrl: false, showPageSelector: true }}
                    scrollToTopOnPageChange={false}
                    useURLForSorting={false}
                    emptyState={emptyState}
                    columns={columns.map(({ key, title, tooltip, width, numeric, sortValue, render }) => ({
                        key,
                        title: numeric ? <span className="whitespace-normal">{title}</span> : title,
                        tooltip,
                        width,
                        align: numeric ? ('right' as const) : undefined,
                        sorter: sortValue
                            ? (a: MarketingAnalyticsSearchRow, b: MarketingAnalyticsSearchRow) =>
                                  sortValue(a) - sortValue(b)
                            : undefined,
                        render: (_: unknown, row: MarketingAnalyticsSearchRow) => render(row),
                    }))}
                />
            )}
        </BindLogic>
    )
}
