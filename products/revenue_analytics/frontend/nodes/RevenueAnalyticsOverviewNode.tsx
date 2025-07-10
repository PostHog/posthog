import { useValues } from 'kea'
import { useState } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { humanFriendlyNumber, range } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { QueryContext } from '~/queries/types'
import {
    AnyResponseType,
    CurrencyCode,
    RevenueAnalyticsOverviewItem,
    RevenueAnalyticsOverviewItemKey,
    RevenueAnalyticsOverviewQuery,
    RevenueAnalyticsOverviewQueryResponse,
} from '~/schema'

import { revenueAnalyticsLogic } from '../revenueAnalyticsLogic'

const NUM_SKELETONS = 3
const HEIGHT_CLASS = 'h-30'

let uniqueNode = 0
export function RevenueAnalyticsOverviewNode(props: {
    query: RevenueAnalyticsOverviewQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `RevenueAnalyticsOverview.${uniqueNode++}`)
    const logic = dataNodeLogic({
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    })

    const { response, responseLoading } = useValues(logic)
    const queryResponse = response as RevenueAnalyticsOverviewQueryResponse | undefined

    const results = responseLoading ? range(NUM_SKELETONS).map(() => undefined) : (queryResponse?.results ?? [])

    return (
        <div className="flex w-full flex-row flex-wrap gap-2 md:flex-nowrap">
            <div className={cn(HEIGHT_CLASS, 'md:flex-2 w-full md:w-auto md:max-w-[60%]')}>
                <ItemCell item={results[0]} />
            </div>
            <div className="flex flex-1 flex-row flex-wrap gap-2 md:flex-nowrap">
                {results.slice(1).map((item, index) => (
                    <div key={item?.key ?? index} className={cn(HEIGHT_CLASS, 'min-w-[200px] flex-1')}>
                        <ItemCell item={item} />
                    </div>
                ))}
            </div>
        </div>
    )
}

const ItemCell = ({ item }: { item?: RevenueAnalyticsOverviewItem }): JSX.Element => {
    const { baseCurrency } = useValues(teamLogic)
    const {
        dateFilter: { dateFrom, dateTo },
    } = useValues(revenueAnalyticsLogic)

    const label: React.ReactNode = item ? (
        <div className="py-1 text-xs font-bold uppercase">{labelFromKey(item.key, dateFrom, dateTo)}</div>
    ) : (
        <LemonSkeleton className="h-4 w-1/2" />
    )
    const value: React.ReactNode = item ? (
        <div
            className={cn(
                'flex w-full flex-1 items-center justify-center',
                item.key === 'revenue' ? 'text-4xl' : 'text-2xl'
            )}
        >
            {formatItem(item, baseCurrency)}
        </div>
    ) : (
        <LemonSkeleton className="h-8 w-1/3" />
    )

    return (
        <div className="bg-surface-primary flex h-full w-full flex-col items-center justify-around rounded border p-2 text-center">
            {label}
            {value}
        </div>
    )
}

const formatItem = (item: RevenueAnalyticsOverviewItem, currency: CurrencyCode): string => {
    if (item.key === 'paying_customer_count') {
        return item.value.toLocaleString()
    }

    const { symbol, isPrefix } = getCurrencySymbol(currency)
    return `${isPrefix ? symbol : ''}${humanFriendlyNumber(item.value, 2, 2)}${isPrefix ? '' : ' ' + symbol}`
}

const LABEL_FROM_KEY: Record<RevenueAnalyticsOverviewItemKey, string> = {
    revenue: 'Revenue',
    paying_customer_count: 'Distinct paying customers',
    avg_revenue_per_customer: 'Avg. revenue per customer',
}

const labelFromKey = (key: RevenueAnalyticsOverviewItemKey, dateFrom: string | null, dateTo: string | null): string => {
    // If it's a monthly period, then show the MRR label
    if (key === 'revenue' && dateFrom?.match(/^(-?\d+mStart)$/) && dateTo?.match(/^(-?\d+mEnd)$/)) {
        return 'MRR'
    }

    // If we're looking at an "all" (All time) period, then show LTV for revenue per customer
    if (key === 'avg_revenue_per_customer' && dateFrom === 'all') {
        return 'LTV'
    }

    return LABEL_FROM_KEY[key]
}
