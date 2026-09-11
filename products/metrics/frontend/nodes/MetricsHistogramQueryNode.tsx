import { BuiltLogic, LogicWrapper, useValues } from 'kea'
import { useState } from 'react'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { AnyResponseType, MetricsHistogramQuery, MetricsHistogramQueryResponse } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { HeatmapPanel } from '../panels/HeatmapPanel'

let uniqueNode = 0

/** Renders a `MetricsHistogramQuery` (a latency-over-time heatmap) wherever the generic `Query`
 * component is used — saved insights, dashboard tiles, notebooks. */
export function MetricsHistogramQueryNode(props: {
    query: MetricsHistogramQuery
    cachedResults?: AnyResponseType
    context: QueryContext
    attachTo?: LogicWrapper | BuiltLogic
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `MetricsHistogramQueryNode.${uniqueNode++}`)
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
    const histogram = response as MetricsHistogramQueryResponse | undefined
    const unit = props.query.unit

    return (
        <div className="relative flex flex-col w-full h-full min-h-[200px]">
            {histogram && histogram.times?.length ? (
                <HeatmapPanel response={histogram} unit={unit} />
            ) : !responseLoading ? (
                <div className="flex-1 flex items-center justify-center text-secondary text-sm">
                    No data for this metric in the selected range.
                </div>
            ) : null}
            {responseLoading && <SpinnerOverlay />}
        </div>
    )
}
