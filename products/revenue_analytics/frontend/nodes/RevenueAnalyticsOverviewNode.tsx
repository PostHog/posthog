import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { humanFriendlyNumber, range } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    CurrencyCode,
    RevenueAnalyticsOverviewItem,
    RevenueAnalyticsOverviewItemKey,
    RevenueAnalyticsOverviewQuery,
    RevenueAnalyticsOverviewQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

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
        <div className="flex flex-row flex-wrap md:flex-nowrap w-full gap-2">
            <div className={cn(HEIGHT_CLASS, 'w-full md:flex-2 md:w-auto md:max-w-[60%]')}>
                <ItemCell item={results[0]} />
            </div>
            <div className="flex flex-row gap-2 flex-1 flex-wrap md:flex-nowrap">
                {results.slice(1).map((item, index) => (
                    <div key={item?.key ?? index} className={cn(HEIGHT_CLASS, 'flex-1 min-w-[200px]')}>
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
        <div className="font-bold uppercase text-xs py-1">{labelFromKey(item.key, dateFrom, dateTo)}</div>
    ) : (
        <LemonSkeleton className="w-1/2 h-4" />
    )
    const value: React.ReactNode = item ? (
        <div
            className={cn(
                'w-full flex-1 flex items-center justify-center',
                item.key === 'revenue' ? 'text-4xl' : 'text-2xl'
            )}
        >
            {formatItem(item, baseCurrency)}
        </div>
    ) : (
        <LemonSkeleton className="w-1/3 h-8" />
    )

    return (
        <div className="flex flex-col items-center text-center justify-around w-full h-full border p-2 bg-surface-primary rounded">
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
