import { BindLogic, useValues } from 'kea'
import { useState } from 'react'

import { dayjs } from 'lib/dayjs'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { InsightLoadingState } from 'scenes/insights/EmptyStates'
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
import { RevenueAnalyticsLineGraph, TileProps, TileWrapper, extractLabelAndDatasets } from './shared'

let uniqueNode = 0
export function RevenueAnalyticsGrossRevenueNode(props: {
    query: RevenueAnalyticsGrossRevenueQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `RevenueAnalyticsGrossRevenue.${uniqueNode++}`)
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
                    response={response as RevenueAnalyticsGrossRevenueQueryResponse}
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
}: TileProps<RevenueAnalyticsGrossRevenueQueryResponse>): JSX.Element => {
    const { baseCurrency, revenueGoals, groupBy } = useValues(revenueAnalyticsLogic)
    const { isPrefix, symbol: currencySymbol } = getCurrencySymbol(baseCurrency)

    const results = (response?.results as GraphDataset[]) ?? []
    const { labels, datasets } = extractLabelAndDatasets(results)

    return (
        <TileWrapper
            title="Gross Revenue"
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
            {responseLoading ? (
                <InsightLoadingState queryId={queryId} key={queryId} insightProps={context.insightProps ?? {}} />
            ) : (
                <RevenueAnalyticsLineGraph
                    data-attr="revenue-analytics-revenue-tile-graph"
                    datasets={datasets}
                    labels={labels}
                    legend={{
                        display: groupBy.length > 0 && datasets.length > 1,
                        position: 'right',
                        // By default chart.js renders first item at the bottom of stack, but legend goes at the top, let's reverse the legend instead
                        reverse: true,
                    }}
                    trendsFilter={{
                        aggregationAxisFormat: 'numeric',
                        aggregationAxisPrefix: isPrefix ? currencySymbol : undefined,
                        aggregationAxisPostfix: isPrefix ? undefined : currencySymbol,
                        goalLines: revenueGoals.map((goal) => {
                            const isFuture = dayjs(goal.due_date).isSameOrAfter(dayjs())

                            return {
                                label: `${goal.name} (${dayjs(goal.due_date).format('DD MMM YYYY')})`,
                                value: goal.goal,
                                displayLabel: true,
                                borderColor: isFuture ? 'green' : 'red',

                                // Only display smaller goals that are in the future
                                // This implies that past goals that have been achieved already
                                // will not be displayed
                                displayIfCrossed: isFuture,
                            }
                        }),
                    }}
                />
            )}
        </TileWrapper>
    )
}
