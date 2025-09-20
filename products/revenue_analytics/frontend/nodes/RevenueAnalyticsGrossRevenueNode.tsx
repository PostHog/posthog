import { BindLogic, BuiltLogic, LogicWrapper, useValues } from 'kea'
import { useState } from 'react'

import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    RevenueAnalyticsGrossRevenueQuery,
    RevenueAnalyticsGrossRevenueQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { GraphDataset } from '~/types'

import { revenueAnalyticsLogic } from '../revenueAnalyticsLogic'
import {
    RevenueAnalyticsLineGraph,
    TileProps,
    TileWrapper,
    extractLabelAndDatasets,
    goalLinesFromRevenueGoals,
} from './shared'

let uniqueNode = 0

export function RevenueAnalyticsGrossRevenueNode(props: {
    query: RevenueAnalyticsGrossRevenueQuery
    cachedResults?: AnyResponseType
    context: QueryContext
    attachTo?: LogicWrapper | BuiltLogic
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `RevenueAnalyticsGrossRevenue.${uniqueNode++}`)
    const dataNodeLogicProps = {
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    }

    useAttachedLogic(insightLogic(props.context.insightProps ?? {}), props.attachTo)
    useAttachedLogic(insightVizDataLogic(props.context.insightProps ?? {}), props.attachTo)
    useAttachedLogic(dataNodeLogic(dataNodeLogicProps), props.attachTo)

    return (
        <BindLogic logic={insightLogic} props={props.context.insightProps ?? {}}>
            <BindLogic logic={insightVizDataLogic} props={props.context.insightProps ?? {}}>
                <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                    <Tile context={props.context} />
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

const Tile = ({ context }: TileProps): JSX.Element => {
    const { baseCurrency, revenueGoals, breakdownProperties } = useValues(revenueAnalyticsLogic)
    const { isPrefix, symbol: currencySymbol } = getCurrencySymbol(baseCurrency)

    return (
        <TileWrapper
            context={context}
            title="Gross revenue"
            tooltip={
                <span>
                    Gross revenue is the total amount of revenue generated from all sources, including all products and
                    services.
                    <br />
                    <br />
                    For Stripe sources, we're automatically calculating deferred revenue which implies you might see
                    revenue in the future if you've created an invoice item with a <code>period.start</code> and{' '}
                    <code>period.end</code> that spans several months.
                </span>
            }
        >
            {(rawResponse) => {
                const response = rawResponse as RevenueAnalyticsGrossRevenueQueryResponse | null
                const results = (response?.results as GraphDataset[]) ?? []
                const { labels, datasets } = extractLabelAndDatasets(results)
                return (
                    <RevenueAnalyticsLineGraph
                        data-attr="revenue-analytics-revenue-tile-graph"
                        datasets={datasets}
                        labels={labels}
                        legend={{
                            display: breakdownProperties.length > 0 && datasets.length > 1,
                            position: 'right',
                            // By default chart.js renders first item at the bottom of stack, but legend goes at the top, let's reverse the legend instead
                            reverse: true,
                        }}
                        trendsFilter={{
                            aggregationAxisFormat: 'numeric',
                            aggregationAxisPrefix: isPrefix ? currencySymbol : undefined,
                            aggregationAxisPostfix: isPrefix ? undefined : currencySymbol,
                            goalLines: goalLinesFromRevenueGoals(revenueGoals, 'gross'),
                        }}
                    />
                )
            }}
        </TileWrapper>
    )
}
