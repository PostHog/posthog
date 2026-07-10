import { BuiltLogic, LogicWrapper, useValues } from 'kea'
import { useState } from 'react'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { AnyResponseType, MetricsQuery, MetricsQueryResponse } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { MetricsSeriesChart } from '../components/MetricsSeriesChart'

let uniqueNode = 0

/** Renders a `MetricsQuery` wherever the generic `Query` component is used —
 * saved insights, dashboard tiles, notebooks. */
export function MetricsQueryNode(props: {
    query: MetricsQuery
    cachedResults?: AnyResponseType
    context: QueryContext
    attachTo?: LogicWrapper | BuiltLogic
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `MetricsQueryNode.${uniqueNode++}`)
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
    const queryResponse = response as MetricsQueryResponse | undefined
    const series = queryResponse?.results ?? []
    const hasPoints = series.some((s) => s.points.length > 0)
    const fallbackName = props.query.clauses[0]?.metricName ?? 'metric'

    return (
        <div className="relative flex flex-col w-full h-full min-h-[200px]">
            {hasPoints ? (
                <MetricsSeriesChart
                    series={series.map((s) => ({ labels: s.labels, points: s.points, metricName: s.metricName }))}
                    fallbackName={fallbackName}
                    className="flex flex-col w-full h-full"
                />
            ) : !responseLoading ? (
                <div className="flex-1 flex items-center justify-center text-secondary text-sm">
                    No data for this metric in the selected range.
                </div>
            ) : null}
            {responseLoading && <SpinnerOverlay />}
        </div>
    )
}
