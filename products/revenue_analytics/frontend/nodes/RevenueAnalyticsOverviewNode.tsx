import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { humanFriendlyNumber, range } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { revenueEventsSettingsLogic } from 'products/revenue_analytics/frontend/settings/revenueEventsSettingsLogic'
import { useState } from 'react'

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
const REVENUE_CONTAINER_CLASS = 'col-span-3'

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

    return (
        <div className="grid auto-cols-fr grid-flow-col w-full gap-2">
            {responseLoading
                ? range(NUM_SKELETONS).map((index) => (
                      <LemonSkeleton
                          key={index}
                          className={cn(HEIGHT_CLASS, { [REVENUE_CONTAINER_CLASS]: index === 0 })}
                      />
                  ))
                : queryResponse?.results?.map((item, index) => (
                      <div key={item.key} className={cn(HEIGHT_CLASS, { [REVENUE_CONTAINER_CLASS]: index === 0 })}>
                          <ItemCell item={item} />
                      </div>
                  ))}
        </div>
    )
}

const ItemCell = ({ item }: { item: RevenueAnalyticsOverviewItem }): JSX.Element => {
    const { baseCurrency } = useValues(revenueEventsSettingsLogic)
    const {
        dateFilter: { dateFrom },
    } = useValues(revenueAnalyticsLogic)

    const label = labelFromKey(item.key, dateFrom)

    return (
        <div className="flex flex-col items-center text-center justify-between w-full h-full border p-2 bg-surface-primary rounded">
            <div className="font-bold uppercase text-xs py-1">{label}&nbsp;&nbsp;</div>
            <div className="w-full flex-1 flex items-center justify-center">
                <div className={cn(item.key === 'revenue' ? 'text-4xl' : 'text-2xl')}>
                    {formatItem(item, baseCurrency)}
                </div>
            </div>
        </div>
    )
}

const formatItem = (item: RevenueAnalyticsOverviewItem, currency?: CurrencyCode): string => {
    if (item.key === 'paying_customer_count') {
        return item.value.toLocaleString()
    }

    const { symbol, isPrefix } = getCurrencySymbol(currency ?? CurrencyCode.USD)
    return `${isPrefix ? symbol : ''}${humanFriendlyNumber(item.value, 2, 2)}${isPrefix ? '' : ' ' + symbol}`
}

const LABEL_FROM_KEY: Record<RevenueAnalyticsOverviewItemKey, string> = {
    revenue: 'Revenue',
    paying_customer_count: 'Paying customers',
    avg_revenue_per_customer: 'Revenue per customer',
}

const labelFromKey = (key: RevenueAnalyticsOverviewItemKey, dateFrom: string | null): string => {
    // TODO: Update once we have a better way to handle this
    if (key === 'revenue' && dateFrom === '-30d') {
        return 'MRR'
    }

    return LABEL_FROM_KEY[key]
}
