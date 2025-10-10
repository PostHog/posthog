import { BuiltLogic, LogicWrapper, useValues } from 'kea'
import { useState } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { cn } from 'lib/utils/css-classes'
import { formatCurrency } from 'lib/utils/geography/currency'
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

const HEIGHT_CLASS = 'h-30'

const LABEL_FROM_KEY: Record<RevenueAnalyticsOverviewItemKey, string> = {
    revenue: 'Revenue',
    paying_customer_count: 'Distinct paying customers',
    avg_revenue_per_customer: 'Avg. Revenue per paying customer',
}

type Item = {
    key: RevenueAnalyticsOverviewItemKey
    label: string
    loading: boolean
    item?: RevenueAnalyticsOverviewItem
}

let uniqueNode = 0
export function RevenueAnalyticsOverviewNode(props: {
    query: RevenueAnalyticsOverviewQuery
    cachedResults?: AnyResponseType
    context: QueryContext
    attachTo?: LogicWrapper | BuiltLogic
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

    useAttachedLogic(logic, props.attachTo)

    const { response, responseLoading } = useValues(logic)
    const queryResponse = response as RevenueAnalyticsOverviewQueryResponse | undefined

    const responseByKey = (queryResponse?.results?.reduce(
        (acc, item) => {
            acc[item.key] = item
            return acc
        },
        {} as Record<RevenueAnalyticsOverviewItemKey, RevenueAnalyticsOverviewItem>
    ) ?? {}) as Record<RevenueAnalyticsOverviewItemKey, RevenueAnalyticsOverviewItem>

    const results: Item[] = Object.entries(LABEL_FROM_KEY).map(([key, label]) => ({
        key: key as RevenueAnalyticsOverviewItemKey,
        label,
        loading: responseLoading,
        item: responseByKey[key as RevenueAnalyticsOverviewItemKey],
    }))

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

const ItemCell = ({ item }: { item: Item }): JSX.Element => {
    const { baseCurrency } = useValues(teamLogic)

    const value: React.ReactNode = item.loading ? (
        <LemonSkeleton className="w-1/3 h-8" />
    ) : (
        <div
            className={cn(
                'w-full flex-1 flex items-center justify-center',
                item.key === 'revenue' ? 'text-4xl' : 'text-2xl'
            )}
        >
            {item.item ? (
                formatItem(item.item, baseCurrency)
            ) : (
                <span className="text-danger text-xs">Error loading data</span>
            )}
        </div>
    )

    return (
        <div className="flex flex-col items-center text-center justify-around w-full h-full border p-2 bg-surface-primary rounded">
            <div className="font-bold uppercase text-xs py-1">{item.label}</div>
            {value}
        </div>
    )
}

const formatItem = (item: RevenueAnalyticsOverviewItem, currency: CurrencyCode): string => {
    if (item.key === 'paying_customer_count') {
        return item.value.toLocaleString()
    }

    return formatCurrency(item.value, currency)
}
