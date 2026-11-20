import { BuiltLogic, LogicWrapper, useValues } from 'kea'
import { useState } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { cn } from 'lib/utils/css-classes'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    EndpointsUsageOverviewItem,
    EndpointsUsageOverviewItemKey,
    EndpointsUsageOverviewQuery,
    EndpointsUsageOverviewQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { ENDPOINTS_USAGE_OVERVIEW_LABELS, formatEndpointsUsageOverviewValue } from './endpointsUsageOverviewFormat'
import { QuillEndpointsUsageOverview } from './QuillEndpointsUsageOverview'

const HEIGHT_CLASS = 'h-24'

type MetricKey = EndpointsUsageOverviewItemKey

const LABEL_FROM_KEY = ENDPOINTS_USAGE_OVERVIEW_LABELS

const PRIMARY_METRICS: MetricKey[] = ['total_requests', 'total_bytes_read', 'total_cpu_seconds']
const SECONDARY_METRICS: MetricKey[] = [
    'avg_query_duration_ms',
    'p95_query_duration_ms',
    'error_rate',
    'materialized_requests',
    'inline_requests',
]

type Item = {
    key: MetricKey
    label: string
    loading: boolean
    item?: EndpointsUsageOverviewItem
}

let uniqueNode = 0
export function EndpointsUsageOverviewNode(props: {
    query: EndpointsUsageOverviewQuery
    cachedResults?: AnyResponseType
    context: QueryContext
    attachTo?: LogicWrapper | BuiltLogic
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `EndpointsUsageOverview.${uniqueNode++}`)
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
    const queryResponse = response as EndpointsUsageOverviewQueryResponse | undefined
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillEndpointsUsageOverview results={queryResponse?.results} loading={responseLoading} />
    }

    const responseByKey = (queryResponse?.results?.reduce(
        (acc, item) => {
            acc[item.key as MetricKey] = item
            return acc
        },
        {} as Record<MetricKey, EndpointsUsageOverviewItem>
    ) ?? {}) as Record<MetricKey, EndpointsUsageOverviewItem>

    const primaryResults: Item[] = PRIMARY_METRICS.map((metricKey) => ({
        key: metricKey,
        label: LABEL_FROM_KEY[metricKey],
        loading: responseLoading,
        item: responseByKey[metricKey],
    }))

    const secondaryResults: Item[] = SECONDARY_METRICS.map((metricKey) => ({
        key: metricKey,
        label: LABEL_FROM_KEY[metricKey],
        loading: responseLoading,
        item: responseByKey[metricKey],
    }))

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-row flex-wrap md:flex-nowrap w-full gap-2">
                {primaryResults.map((item, index) => (
                    <div key={item?.key ?? index} className={cn(HEIGHT_CLASS, 'flex-1 min-w-[200px]')}>
                        <ItemCell item={item} isPrimary />
                    </div>
                ))}
            </div>
            <div className="flex flex-row flex-wrap md:flex-nowrap w-full gap-2">
                {secondaryResults.map((item, index) => (
                    <div key={item?.key ?? index} className={cn(HEIGHT_CLASS, 'flex-1 min-w-[150px]')}>
                        <ItemCell item={item} isPrimary={false} />
                    </div>
                ))}
            </div>
        </div>
    )
}

const ItemCell = ({ item, isPrimary }: { item: Item; isPrimary: boolean }): JSX.Element => {
    const value: React.ReactNode = item.loading ? (
        <LemonSkeleton className="w-1/3 h-6" />
    ) : (
        <div
            className={cn(
                'w-full flex-1 flex items-center justify-center',
                isPrimary ? 'text-2xl font-bold' : 'text-xl'
            )}
        >
            {item.item ? (
                formatEndpointsUsageOverviewValue(item.item.key, item.item.value)
            ) : (
                <span className="text-muted text-sm">No data</span>
            )}
        </div>
    )

    // TODO: See how Web Analytics does this
    const changeIndicator =
        !item.loading && item.item?.changeFromPreviousPct != null ? (
            <div
                className={cn(
                    'text-xs',
                    item.item.changeFromPreviousPct > 0
                        ? 'text-success'
                        : item.item.changeFromPreviousPct < 0
                          ? 'text-danger'
                          : 'text-muted'
                )}
            >
                {item.item.changeFromPreviousPct > 0 ? '+' : ''}
                {item.item.changeFromPreviousPct.toFixed(1)}%
            </div>
        ) : null

    return (
        <div className="flex flex-col items-center text-center justify-around w-full h-full border p-2 bg-surface-primary rounded">
            <div className="font-medium text-xs text-muted uppercase">{item.label}</div>
            {value}
            {changeIndicator}
        </div>
    )
}
