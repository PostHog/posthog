import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { IconSwapHoriz } from 'lib/lemon-ui/icons'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { InsightLoadingState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    RevenueAnalyticsMRRQuery,
    RevenueAnalyticsMRRQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { GraphDataset } from '~/types'

import { revenueAnalyticsLogic } from '../revenueAnalyticsLogic'
import { AlphaTag, RevenueAnalyticsLineGraph, TileProps, TileWrapper, extractLabelAndDatasets } from './shared'

let uniqueNode = 0
export function RevenueAnalyticsMRRNode(props: {
    query: RevenueAnalyticsMRRQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `RevenueAnalyticsMRR.${uniqueNode++}`)
    const logic = dataNodeLogic({
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    })

    const { response, responseLoading, queryId } = useValues(logic)

    return (
        <BindLogic logic={insightLogic} props={props.context.insightProps ?? {}}>
            <BindLogic logic={insightVizDataLogic} props={props.context.insightProps ?? {}}>
                <Tile
                    response={response as RevenueAnalyticsMRRQueryResponse}
                    responseLoading={responseLoading}
                    queryId={queryId ?? ''}
                    context={props.context}
                />
            </BindLogic>
        </BindLogic>
    )
}

const Tile = ({
    response,
    responseLoading,
    queryId,
    context,
}: TileProps<RevenueAnalyticsMRRQueryResponse>): JSX.Element => {
    const { baseCurrency, groupBy, mrrMode } = useValues(revenueAnalyticsLogic)
    const { setMRRMode } = useActions(revenueAnalyticsLogic)

    const { isPrefix, symbol: currencySymbol } = getCurrencySymbol(baseCurrency)

    const results = (response?.results?.map((mrr) => mrr.total) as GraphDataset[]) ?? []

    const { labels, datasets } = extractLabelAndDatasets(results)

    const mappedDatasets: GraphDataset[] = datasets.map((dataset) => ({
        ...dataset,
        data: dataset.data.map((value) => {
            if (typeof value !== 'number' || mrrMode === 'mrr') {
                return value
            }

            return value * 12
        }) as GraphDataset['data'], // Dumb type assertion because TS can't infer the type of the data
    }))

    return (
        <TileWrapper
            title={
                <>
                    <LemonButton
                        icon={<IconSwapHoriz />}
                        onClick={() => setMRRMode(mrrMode === 'mrr' ? 'arr' : 'mrr')}
                        tooltip={mrrMode === 'mrr' ? 'Switch to ARR' : 'Switch to MRR'}
                        type="secondary"
                        size="small"
                    >
                        <span className="font-semibold">{mrrMode === 'mrr' ? 'MRR' : 'ARR'}</span>
                    </LemonButton>
                </>
            }
            tooltip="MRR is the total amount of recurring revenue generated from all sources, including all products and services in the last 30 days. ARR is that value multiplied by 12."
            extra={
                <span className="flex items-center">
                    <AlphaTag />
                </span>
            }
        >
            {responseLoading ? (
                <InsightLoadingState queryId={queryId} key={queryId} insightProps={context.insightProps ?? {}} />
            ) : (
                <RevenueAnalyticsLineGraph
                    data-attr="revenue-analytics-mrr-tile-graph"
                    datasets={mappedDatasets}
                    labels={labels}
                    legend={{
                        display: groupBy.length > 0 && mappedDatasets.length > 1,
                        position: 'right',
                        // By default chart.js renders first item at the bottom of stack, but legend goes at the top, let's reverse the legend instead
                        reverse: true,
                    }}
                    trendsFilter={{
                        aggregationAxisFormat: 'numeric',
                        aggregationAxisPrefix: isPrefix ? currencySymbol : undefined,
                        aggregationAxisPostfix: isPrefix ? undefined : currencySymbol,
                    }}
                />
            )}
        </TileWrapper>
    )
}
